"""
PolyBoquette - Backend Flask
==============================
Lance avec : python server.py
En production : gunicorn server:app --bind 0.0.0.0:8000

Architecture :
- Données persistées dans PostgreSQL si DATABASE_URL est défini (Render)
- Fallback sur data/db.json en local (développement)
- Sessions via cookie signé Flask
- Routes REST : /api/...
- Le frontend (index.html + assets) est servi directement par Flask
"""

import os
import copy
import json
import secrets
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, abort

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "data")
DB_PATH    = os.path.join(DATA_DIR, "db.json")
STATIC_DIR = BASE_DIR          # index.html est à la racine de PolyBoquette/

app = Flask(__name__)

# Clé secrète – remplace par une vraie valeur en prod (variable d'env)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

PALETTE = ['#22c55e', '#ef4444', '#3b82f6', '#d946ef', '#f97316', '#eab308', '#06b6d4']

# ──────────────────────────────────────────────────────────────────────────────
# PERSISTANCE : PostgreSQL (prod) ou JSON (local)
# ──────────────────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL")  # mis à dispo automatiquement par Render
USE_PG = PSYCOPG2_AVAILABLE and bool(DATABASE_URL)

DEFAULT_DB = {
    "version": 5,
    "users": {
        "admin": {
            "id": "admin", "username": "admin", "password": "***admin123***",
            "name": "ADMIN", "role": "admin", "status": "active",
            "points": 1000, "buque": "Admin", "nums": "1", "proms": "Me225",
            "transactions": []
        }
    },
    "markets": [],
    "proposals": []
}



def _get_pg_conn():
    """Retourne une connexion PostgreSQL."""
    return psycopg2.connect(DATABASE_URL)


def _ensure_pg_table(conn):
    """Crée la table si elle n'existe pas encore."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS polyboquette_db (
                id INTEGER PRIMARY KEY DEFAULT 1,
                data TEXT NOT NULL
            )
        """)
    conn.commit()


def _migrate(db):
    """Applique les migrations sur une DB chargée."""
    if "proposals" not in db:
        db["proposals"] = []
    for u in db["users"].values():
        if "transactions" not in u:
            u["transactions"] = []
    return db


def load_db():
    if USE_PG:
        try:
            conn = _get_pg_conn()
            _ensure_pg_table(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM polyboquette_db WHERE id = 1")
                row = cur.fetchone()
            conn.close()
            if row:
                return _migrate(json.loads(row[0]))
            # Première utilisation : initialiser avec DEFAULT_DB
            db = copy.deepcopy(DEFAULT_DB)
            save_db(db)
            return db
        except Exception as e:
            print(f"[PG] Erreur load_db: {e}")
            return copy.deepcopy(DEFAULT_DB)
    else:
        # Mode local : fichier JSON
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(DB_PATH):
            db = copy.deepcopy(DEFAULT_DB)
            save_db(db)
            return db
        with open(DB_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
        return _migrate(db)


def save_db(db):
    if USE_PG:
        try:
            conn = _get_pg_conn()
            _ensure_pg_table(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO polyboquette_db (id, data)
                    VALUES (1, %s)
                    ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
                """, (json.dumps(db, ensure_ascii=False),))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[PG] Erreur save_db: {e}")
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# DECORATEURS AUTH
# ──────────────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Non authentifié"}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Non authentifié"}), 401
        db = load_db()
        user = db["users"].get(session["user_id"])
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Accès refusé"}), 403
        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS METIER
# ──────────────────────────────────────────────────────────────────────────────
def compute_probs(market, exclude_bet=None):
    """Calcule les probabilités proportionnelles aux vraies mises (hors liquidité initiale)."""
    # Utilise les shares UNIQUEMENT issus des mises réelles
    total = sum(o["shares"] for o in market["options"])
    if exclude_bet:
        total -= exclude_bet["amount"]
    if total <= 0:
        # Aucune mise : égalité parfaite
        n = len(market["options"])
        return {o["id"]: round(100 / n) for o in market["options"]}
    result = {}
    for o in market["options"]:
        adj = o["shares"]
        if exclude_bet and o["id"] == exclude_bet["optId"]:
            adj = max(0, adj - exclude_bet["amount"])
        result[o["id"]] = round((adj / total) * 100)
    return result


def safe_user(user):
    """Retourne un dict user sans le mot de passe."""
    u = dict(user)
    u.pop("password", None)
    return u


def add_tx(user, desc, amount):
    if "transactions" not in user:
        user["transactions"] = []
    user["transactions"].insert(0, {
        "time": datetime.now(timezone.utc).isoformat(),
        "desc": desc,
        "amount": amount
    })
    # Garder seulement les 50 dernières
    user["transactions"] = user["transactions"][:50]


# ──────────────────────────────────────────────────────────────────────────────
# ROUTES – FRONTEND (SPA)
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/css/<path:filename>")
def css(filename):
    return send_from_directory(os.path.join(BASE_DIR, "css"), filename)

@app.route("/js/<path:filename>")
def js(filename):
    return send_from_directory(os.path.join(BASE_DIR, "js"), filename)


# ──────────────────────────────────────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/auth/me")
def auth_me():
    if "user_id" not in session:
        return jsonify({"user": None})
    db = load_db()
    user = db["users"].get(session["user_id"])
    if not user:
        session.clear()
        return jsonify({"user": None})
    return jsonify({"user": safe_user(user)})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json()
    db = load_db()
    user = next(
        (u for u in db["users"].values()
         if u["username"] == data.get("username") and u["password"] == data.get("password")),
        None
    )
    if not user:
        return jsonify({"error": "Identifiants incorrects"}), 401
    if user["status"] == "pending":
        return jsonify({"error": "Compte en attente de validation admin"}), 403
    if user["status"] == "rejected":
        return jsonify({"error": "Compte rejeté par l'admin"}), 403
    session["user_id"] = user["id"]
    return jsonify({"user": safe_user(user)})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    name     = data.get("name", "").strip()
    if not username or not password or not name:
        return jsonify({"error": "Nom, identifiant et mot de passe requis"}), 400
    db = load_db()
    if any(u["username"] == username for u in db["users"].values()):
        return jsonify({"error": "Cet identifiant est déjà pris"}), 409
    new_id = "u" + secrets.token_hex(6)
    db["users"][new_id] = {
        "id": new_id, "username": username, "password": password,
        "name": name, "role": "user", "status": "pending", "points": 100,
        "buque": data.get("buque", ""),
        "nums":  data.get("nums",  ""),
        "proms": data.get("proms", ""),
        "transactions": []
    }
    save_db(db)
    return jsonify({"ok": True}), 201


@app.route("/api/auth/change-password", methods=["POST"])
@login_required
def auth_change_password():
    data = request.get_json()
    old_pass = data.get("oldPassword", "").strip()
    new_pass = data.get("newPassword", "").strip()
    db = load_db()
    user = db["users"].get(session["user_id"])
    if not user:
        return jsonify({"error": "Utilisateur introuvable"}), 404
    if user["password"] != old_pass:
        return jsonify({"error": "Ancien mot de passe incorrect"}), 400
    if len(new_pass) < 3:
        return jsonify({"error": "Le nouveau mot de passe est trop court"}), 400
    user["password"] = new_pass
    save_db(db)
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# CLASSEMENT & BONUS QUOTIDIEN
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/leaderboard")
def get_leaderboard():
    db = load_db()
    active = [u for u in db["users"].values() if u.get("status") == "active"]
    ranked = sorted(active, key=lambda u: u.get("points", 0), reverse=True)[:20]
    return jsonify([{"id": u["id"], "name": u["name"], "points": int(u["points"])} for u in ranked])


@app.route("/api/auth/daily-claim", methods=["POST"])
@login_required
def daily_claim():
    db = load_db()
    user = db["users"].get(session["user_id"])
    if not user:
        return jsonify({"error": "Utilisateur introuvable"}), 404
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if user.get("lastClaim") == today:
        return jsonify({"error": "Bonus déjà récupéré aujourd'hui"}), 400
    user["lastClaim"] = today
    user["points"] += 5
    add_tx(user, "Bonus quotidien", 5)
    save_db(db)
    return jsonify({"ok": True, "user": safe_user(user)})


# ──────────────────────────────────────────────────────────────────────────────
# MARCHÉS
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/markets")
def get_markets():
    db = load_db()
    return jsonify(db["markets"])


@app.route("/api/markets/<market_id>")
def get_market(market_id):
    db = load_db()
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m:
        return jsonify({"error": "Introuvable"}), 404
    return jsonify(m)


@app.route("/api/markets/<market_id>/bet", methods=["POST"])
@login_required
def place_bet(market_id):
    data = request.get_json()
    opt_id = data.get("optId")
    amount = data.get("amount", 0)
    db = load_db()

    user = db["users"].get(session["user_id"])
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m:
        return jsonify({"error": "Marché introuvable"}), 404
    if m["status"] != "open":
        return jsonify({"error": "Ce marché n'accepte plus de transactions"}), 400
    if not isinstance(amount, int) or amount <= 0:
        return jsonify({"error": "Montant invalide"}), 400
    if user["points"] < amount:
        return jsonify({"error": "Solde insuffisant"}), 400
    opt = next((o for o in m["options"] if o["id"] == opt_id), None)
    if not opt:
        return jsonify({"error": "Option invalide"}), 400

    user["points"] -= amount
    m["volume"] += amount
    opt["shares"] += amount

    probs = compute_probs(m)
    now_str = datetime.now(timezone.utc).strftime("%H:%M")
    bet = {
        "id": "b" + secrets.token_hex(8),
        "userId": user["id"],
        "optId": opt_id,
        "amount": amount,
        "buyProb": probs[opt_id],
        "time": datetime.now(timezone.utc).isoformat()
    }
    m["bets"].append(bet)
    hist = {"time": now_str, **probs}
    m["history"].append(hist)
    
    add_tx(user, f"Mise dans '{m['title']}'", -amount)

    save_db(db)
    return jsonify({"user": safe_user(user), "market": m})


@app.route("/api/markets/<market_id>/cashout/<bet_id>", methods=["POST"])
@login_required
def cashout_bet(market_id, bet_id):
    db = load_db()
    user = db["users"].get(session["user_id"])
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m or m["status"] != "open":
        return jsonify({"error": "Revente impossible"}), 400
    bet_idx = next((i for i, b in enumerate(m["bets"]) if b["id"] == bet_id), None)
    if bet_idx is None:
        return jsonify({"error": "Pari introuvable"}), 404
    bet = m["bets"][bet_idx]
    if bet["userId"] != user["id"]:
        return jsonify({"error": "Pas votre pari"}), 403

    adj_probs = compute_probs(m, exclude_bet=bet)
    current_prob = adj_probs.get(bet["optId"], 1)
    raw_value = bet["amount"] * (current_prob / (bet["buyProb"] or 1))
    refund = max(1, int(raw_value * 0.97))

    user["points"] += refund
    m["volume"] = max(1, m["volume"] - refund)
    opt = next(o for o in m["options"] if o["id"] == bet["optId"])
    opt["shares"] = max(1, opt["shares"] - refund)

    new_probs = compute_probs(m)
    now_str = datetime.now(timezone.utc).strftime("%H:%M")
    m["history"].append({"time": now_str, **new_probs})
    m["bets"].pop(bet_idx)
    
    add_tx(user, f"Revente dans '{m['title']}'", refund)

    save_db(db)
    return jsonify({"user": safe_user(user), "market": m, "refund": refund})


# ──────────────────────────────────────────────────────────────────────────────
# PROPOSITIONS DE PARIS
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/proposals", methods=["GET"])
@login_required
def get_proposals():
    db = load_db()
    user = db["users"].get(session["user_id"])
    if user["role"] == "admin":
        # L'admin voit tout
        return jsonify(db["proposals"])
    else:
        # Un user voit seulement ses propres propositions
        my = [p for p in db["proposals"] if p["authorId"] == user["id"]]
        return jsonify(my)


@app.route("/api/proposals", methods=["POST"])
@login_required
def submit_proposal():
    data = request.get_json()
    title   = (data.get("title") or "").strip()
    choices = data.get("choices", [])
    image   = (data.get("image") or "").strip()
    db = load_db()
    user = db["users"].get(session["user_id"])

    if not title:
        return jsonify({"error": "Le titre est requis"}), 400
    if len(choices) < 2:
        return jsonify({"error": "Au moins 2 choix requis"}), 400

    proposal = {
        "id": "p" + secrets.token_hex(6),
        "authorId":   user["id"],
        "authorName": user["name"],
        "title":      title,
        "choices":    [c.strip() for c in choices if c.strip()],
        "image":      image,
        "status":     "pending",   # pending | approved | rejected
        "adminNote":  "",
        "createdAt":  datetime.now(timezone.utc).isoformat()
    }
    db["proposals"].append(proposal)
    save_db(db)
    return jsonify(proposal), 201


@app.route("/api/proposals/<proposal_id>/approve", methods=["POST"])
@admin_required
def approve_proposal(proposal_id):
    db = load_db()
    p = next((p for p in db["proposals"] if p["id"] == proposal_id), None)
    if not p:
        return jsonify({"error": "Proposition introuvable"}), 404

    # Créer le marché depuis la proposition
    choices = p["choices"]
    options = [
        {"id": f"o{i+1}", "label": c, "shares": 0, "color": PALETTE[i % len(PALETTE)]}
        for i, c in enumerate(choices)
    ]
    init_probs = {o["id"]: round(100 / len(options)) for o in options}
    new_market = {
        "id": "m" + secrets.token_hex(6),
        "title": p["title"],
        "image": p["image"] or "https://images.unsplash.com/photo-1550565118-3a14e8d0386f?auto=format&fit=crop&w=150&q=80",
        "volume": 0,
        "status": "open",
        "resolvedWinner": None,
        "bets": [],
        "options": options,
        "history": [{"time": "Début", **init_probs}],
        "proposedBy": p["authorId"]
    }
    db["markets"].append(new_market)
    p["status"] = "approved"
    save_db(db)
    return jsonify({"ok": True, "market": new_market})


@app.route("/api/proposals/<proposal_id>/reject", methods=["POST"])
@admin_required
def reject_proposal(proposal_id):
    data = request.get_json() or {}
    db = load_db()
    p = next((p for p in db["proposals"] if p["id"] == proposal_id), None)
    if not p:
        return jsonify({"error": "Proposition introuvable"}), 404
    p["status"] = "rejected"
    p["adminNote"] = data.get("note", "").strip()
    save_db(db)
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN – UTILISATEURS
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/admin/users")
@admin_required
def admin_get_users():
    db = load_db()
    return jsonify([safe_user(u) for u in db["users"].values()])


@app.route("/api/admin/users/<user_id>/approve", methods=["POST"])
@admin_required
def admin_approve_user(user_id):
    db = load_db()
    if user_id not in db["users"]:
        return jsonify({"error": "Introuvable"}), 404
    db["users"][user_id]["status"] = "active"
    save_db(db)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<user_id>/reject", methods=["POST"])
@admin_required
def admin_reject_user(user_id):
    db = load_db()
    if user_id not in db["users"]:
        return jsonify({"error": "Introuvable"}), 404
    db["users"][user_id]["status"] = "rejected"
    save_db(db)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<user_id>/toggle-role", methods=["POST"])
@admin_required
def admin_toggle_role(user_id):
    db = load_db()
    if session["user_id"] != "admin":
        return jsonify({"error": "Seul le super-admin peut modifier les rôles"}), 403
    if user_id not in db["users"] or user_id == "admin":
        return jsonify({"error": "Impossible"}), 400
    user = db["users"][user_id]
    user["role"] = "admin" if user.get("role") != "admin" else "user"
    save_db(db)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<user_id>/grant", methods=["POST"])
@admin_required
def admin_grant_points(user_id):
    data = request.get_json()
    amount = data.get("amount", 0)
    db = load_db()
    if user_id not in db["users"]:
        return jsonify({"error": "Introuvable"}), 404
    if not isinstance(amount, int) or amount == 0:
        return jsonify({"error": "Montant invalide (ne peut pas être zéro)"}), 400
    user = db["users"][user_id]
    user["points"] = max(0, user["points"] + amount)
    desc = f"Crédit admin : +{amount} pts" if amount > 0 else f"Débit admin : {amount} pts"
    add_tx(user, desc, amount)
    save_db(db)
    return jsonify({"ok": True, "points": user["points"]})


@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
@admin_required
def admin_delete_user(user_id):
    if user_id == "admin":
        return jsonify({"error": "Impossible de supprimer le compte super-admin"}), 400
    db = load_db()
    if user_id not in db["users"]:
        return jsonify({"error": "Introuvable"}), 404
    del db["users"][user_id]
    save_db(db)
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN – MARCHÉS
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/admin/markets", methods=["POST"])
@admin_required
def admin_create_market():
    data = request.get_json()
    title   = (data.get("title") or "").strip()
    choices = data.get("choices", [])
    image   = (data.get("image") or "").strip()
    db = load_db()

    if not title or len(choices) < 2:
        return jsonify({"error": "Titre et 2+ choix requis"}), 400

    options = [
        {"id": f"o{i+1}", "label": c.strip(), "shares": 0, "color": PALETTE[i % len(PALETTE)]}
        for i, c in enumerate(choices)
    ]
    n = len(options)
    init_prob = round(100 / n)
    init_probs = {o["id"]: init_prob for o in options}
    new_market = {
        "id": "m" + secrets.token_hex(6),
        "title": title,
        "image": image or "https://images.unsplash.com/photo-1550565118-3a14e8d0386f?auto=format&fit=crop&w=150&q=80",
        "volume": 0, "status": "open", "resolvedWinner": None,
        "bets": [], "options": options,
        "history": [{"time": "Début", **init_probs}]
    }
    db["markets"].append(new_market)
    save_db(db)
    return jsonify(new_market), 201


@app.route("/api/admin/markets/<market_id>/toggle-pause", methods=["POST"])
@admin_required
def admin_toggle_pause(market_id):
    db = load_db()
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m:
        return jsonify({"error": "Introuvable"}), 404
    m["status"] = "paused" if m["status"] == "open" else "open"
    save_db(db)
    return jsonify({"status": m["status"]})


@app.route("/api/admin/markets/<market_id>/resolve", methods=["POST"])
@admin_required
def admin_resolve_market(market_id):
    data = request.get_json()
    winner_id = data.get("winnerId")
    db = load_db()
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m:
        return jsonify({"error": "Introuvable"}), 404

    m["status"] = "resolved"
    m["resolvedWinner"] = winner_id

    # Pool réel = somme des VRAIES mises (hors liquidité initiale fictive)
    real_total_pool = sum(b["amount"] for b in m["bets"])

    if winner_id == "cancelled":
        for b in m["bets"]:
            if b["userId"] in db["users"]:
                db["users"][b["userId"]]["points"] += b["amount"]
                add_tx(db["users"][b["userId"]], f"Remboursement annulation '{m['title']}'", b["amount"])
    else:
        winning_opt = next((o for o in m["options"] if o["id"] == winner_id), None)
        if winning_opt:
            real_winning_pool = sum(b["amount"] for b in m["bets"] if b["optId"] == winner_id)

            if real_winning_pool == 0:
                # Personne n'a misé sur le gagnant → remboursement intégral de tous
                for b in m["bets"]:
                    if b["userId"] in db["users"]:
                        db["users"][b["userId"]]["points"] += b["amount"]
                        add_tx(db["users"][b["userId"]], f"Remboursement (aucun gagnant) '{m['title']}'", b["amount"])
            else:
                # Pari Mutuel pur sur les vraies mises :
                # Chaque gagnant reçoit sa part proportionnelle du VRAI pool total
                for b in m["bets"]:
                    if b["userId"] in db["users"]:
                        if b["optId"] == winner_id:
                            share_pct = b["amount"] / real_winning_pool
                            payout = max(0, int(share_pct * real_total_pool))
                            db["users"][b["userId"]]["points"] += payout
                            add_tx(db["users"][b["userId"]], f"Gain '{m['title']}'", payout)
                        else:
                            add_tx(db["users"][b["userId"]], f"Pari perdu '{m['title']}'", 0)

    save_db(db)
    return jsonify({"ok": True})


@app.route("/api/admin/markets/<market_id>", methods=["DELETE"])
@admin_required
def admin_delete_market(market_id):
    db = load_db()
    idx = next((i for i, m in enumerate(db["markets"]) if m["id"] == market_id), None)
    if idx is None:
        return jsonify({"error": "Introuvable"}), 404
    if db["markets"][idx]["status"] not in ["resolved", "cancelled"]:
        return jsonify({"error": "Seuls les marchés clôturés peuvent être supprimés"}), 400
    db["markets"].pop(idx)
    save_db(db)
    return jsonify({"ok": True})


@app.route("/api/users/<user_id>/transactions")
@login_required
def get_user_transactions(user_id):
    db = load_db()
    me = db["users"].get(session["user_id"])
    # Un user ne peut voir que son propre historique ; les admins voient tout
    if me["id"] != user_id and me.get("role") != "admin":
        return jsonify({"error": "Accès refusé"}), 403
    target = db["users"].get(user_id)
    if not target:
        return jsonify({"error": "Utilisateur introuvable"}), 404
    return jsonify(target.get("transactions", []))


# ──────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"🚀 PolyBoquette démarre sur http://localhost:{port}")
    print(f"   DB : {DB_PATH}")
    app.run(host="0.0.0.0", port=port, debug=debug)
