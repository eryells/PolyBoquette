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
    "version": 6,
    "users": {
        "admin": {
            "id": "admin", "username": "admin", "password": "admin123",
            "name": "ADMIN", "role": "admin", "status": "active",
            "points": 1000, "buque": "BDE", "nums": "1", "proms": "Me221",
            "transactions": []
        }
    },
    "markets": [],
    "categories": [],
    "proposals": [],
    "admin_grants_log": [],
    "name_change_requests": []
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
    if "categories" not in db:
        db["categories"] = []
    if "proposals" not in db:
        db["proposals"] = []
    if "admin_grants_log" not in db:
        db["admin_grants_log"] = []
    if "name_change_requests" not in db:
        db["name_change_requests"] = []
    for u in db["users"].values():
        if "transactions" not in u:
            u["transactions"] = []
    for m in db.get("markets", []):
        if "comments" not in m:
            m["comments"] = []
        if "pauseAt" not in m:
            m["pauseAt"] = None
        if "categoryId" not in m:
            m["categoryId"] = None
        if "order" not in m:
            m["order"] = 0
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


def is_market_open(market):
    if market.get("status") != "open":
        return False
    pause_at = market.get("pauseAt")
    if pause_at:
        now = datetime.now(timezone.utc).isoformat()
        # Handle JS ISO string format mapping
        if pause_at.endswith('Z'):
            pause_at = pause_at[:-1] + '+00:00'
        if now >= pause_at:
            return False
    return True


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
    # Le classement ne concerne que les points non investis
    def free_points(u):
        return max(0, int(u.get("points", 0)))
    ranked = sorted(active, key=lambda u: free_points(u), reverse=True)[:20]
    return jsonify([{"id": u["id"], "name": u["name"], "points": free_points(u)} for u in ranked])


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
@login_required
def get_markets():
    db = load_db()
    return jsonify(db["markets"])


@app.route("/api/categories")
@login_required
def get_categories():
    db = load_db()
    return jsonify(db.get("categories", []))


@app.route("/api/markets/<market_id>")
@login_required
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
    if not is_market_open(m):
        return jsonify({"error": "Ce marché n'accepte plus de transactions (fermé ou en pause)"}), 400
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
    now_iso = datetime.now(timezone.utc).isoformat()

    # Agrégation : fusionner avec une position existante (même user, même option)
    existing = next((b for b in m["bets"] if b["userId"] == user["id"] and b["optId"] == opt_id), None)
    if existing:
        old_amount = existing["amount"]
        new_total = old_amount + amount
        # Moyenne pondérée du prix d'achat
        existing["buyProb"] = round((existing["buyProb"] * old_amount + probs[opt_id] * amount) / new_total)
        existing["amount"] = new_total
        existing["time"] = now_iso
    else:
        bet = {
            "id": "b" + secrets.token_hex(8),
            "userId": user["id"],
            "optId": opt_id,
            "amount": amount,
            "buyProb": probs[opt_id],
            "time": now_iso
        }
        m["bets"].append(bet)

    hist = {"time": now_iso, **probs}
    m["history"].append(hist)

    add_tx(user, f"Mise dans '{m['title']}'", -amount)

    save_db(db)
    return jsonify({"user": safe_user(user), "market": m})


@app.route("/api/markets/<market_id>/cashout/<bet_id>", methods=["POST"])
@login_required
def cashout_bet(market_id, bet_id):
    data = request.get_json() or {}
    db = load_db()
    user = db["users"].get(session["user_id"])
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m or not is_market_open(m):
        return jsonify({"error": "Revente impossible (marché fermé ou en pause)"}), 400
    bet_idx = next((i for i, b in enumerate(m["bets"]) if b["id"] == bet_id), None)
    if bet_idx is None:
        return jsonify({"error": "Pari introuvable"}), 404
    bet = m["bets"][bet_idx]
    if bet["userId"] != user["id"]:
        return jsonify({"error": "Pas votre pari"}), 403

    # Revente partielle : montant optionnel, défaut = tout
    requested = data.get("amount", bet["amount"])
    if not isinstance(requested, int) or requested <= 0:
        requested = bet["amount"]
    partial_amount = min(requested, bet["amount"])

    # Calcul du remboursement proportionnel
    partial_bet_proxy = {"amount": partial_amount, "optId": bet["optId"]}
    adj_probs = compute_probs(m, exclude_bet=partial_bet_proxy)
    current_prob = adj_probs.get(bet["optId"], 1)
    raw_value = partial_amount * (current_prob / (bet["buyProb"] or 1))
    refund = max(1, int(raw_value * 0.97))

    user["points"] += refund
    m["volume"] = max(0, m["volume"] - partial_amount)
    opt = next(o for o in m["options"] if o["id"] == bet["optId"])
    opt["shares"] = max(0, opt["shares"] - partial_amount)

    now_iso = datetime.now(timezone.utc).isoformat()
    new_probs = compute_probs(m)
    m["history"].append({"time": now_iso, **new_probs})

    if partial_amount >= bet["amount"]:
        m["bets"].pop(bet_idx)
    else:
        bet["amount"] -= partial_amount

    add_tx(user, f"Revente dans '{m['title']}'", refund)

    save_db(db)
    return jsonify({"user": safe_user(user), "market": m, "refund": refund})


@app.route("/api/markets/<market_id>/comments", methods=["POST"])
@login_required
def post_comment(market_id):
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Commentaire vide"}), 400
        
    db = load_db()
    user = db["users"].get(session["user_id"])
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m:
        return jsonify({"error": "Marché introuvable"}), 404
        
    if "comments" not in m:
        m["comments"] = []
        
    comment = {
        "id": "c" + secrets.token_hex(6),
        "userId": user["id"],
        "userName": user["name"],
        "text": text,
        "time": datetime.now(timezone.utc).isoformat()
    }
    m["comments"].append(comment)
    save_db(db)
    return jsonify({"ok": True, "comment": comment})


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
    admin_user = db["users"].get(session["user_id"])
    user = db["users"][user_id]
    user["points"] = max(0, user["points"] + amount)
    desc = f"Crédit admin : +{amount} pts" if amount > 0 else f"Débit admin : {amount} pts"
    add_tx(user, desc, amount)
    # Journaliser dans admin_grants_log
    db["admin_grants_log"].insert(0, {
        "time": datetime.now(timezone.utc).isoformat(),
        "adminId": admin_user["id"],
        "adminName": admin_user["name"],
        "targetId": user["id"],
        "targetName": user["name"],
        "amount": amount
    })
    db["admin_grants_log"] = db["admin_grants_log"][:200]
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
    category_id = data.get("categoryId")
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
        "categoryId": category_id,
        "order": 999,
        "history": [{"time": "Début", **init_probs}]
    }
    db["markets"].append(new_market)
    save_db(db)
    return jsonify(new_market), 201


@app.route("/api/admin/markets/<market_id>/toggle-pause", methods=["POST"])
@admin_required
def admin_toggle_pause(market_id):
    data = request.get_json() or {}
    db = load_db()
    m = next((m for m in db["markets"] if m["id"] == market_id), None)
    if not m:
        return jsonify({"error": "Introuvable"}), 404
        
    if m["status"] == "open":
        pause_at = data.get("pauseAt")
        if pause_at == "now":
            m["status"] = "paused"
            m["pauseAt"] = None
        else:
            m["pauseAt"] = pause_at # ISO string future date
    else:
        m["status"] = "open"
        m["pauseAt"] = None
        
    save_db(db)
    return jsonify({"status": m["status"], "pauseAt": m.get("pauseAt")})


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
# ADMIN - CATÉGORIES & REORDERING
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/admin/categories", methods=["GET", "POST"])
@admin_required
def admin_categories():
    db = load_db()
    if request.method == "GET":
        return jsonify(db.get("categories", []))
        
    # POST
    data = request.get_json()
    action = data.get("action")
    if action == "create":
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Nom requis"}), 400
        new_cat = {
            "id": "cat_" + secrets.token_hex(4),
            "name": name,
            "order": len(db.get("categories", []))
        }
        if "categories" not in db:
            db["categories"] = []
        db["categories"].append(new_cat)
        save_db(db)
        return jsonify({"ok": True, "category": new_cat})
    elif action == "delete":
        cat_id = data.get("id")
        db["categories"] = [c for c in db.get("categories", []) if c["id"] != cat_id]
        # Reset market categories that were in this category
        for m in db["markets"]:
            if m.get("categoryId") == cat_id:
                m["categoryId"] = None
        save_db(db)
        return jsonify({"ok": True})
    return jsonify({"error": "Action inconnue"}), 400


@app.route("/api/admin/markets/reorder", methods=["POST"])
@admin_required
def admin_reorder_markets():
    data = request.get_json()
    categories = data.get("categories", []) # list of {id, order}
    markets = data.get("markets", []) # list of {id, categoryId, order}
    
    db = load_db()
    if "categories" not in db:
        db["categories"] = []
        
    # Update categories order
    for c_data in categories:
        c = next((c for c in db["categories"] if c["id"] == c_data["id"]), None)
        if c:
            c["order"] = c_data["order"]
            
    # Update markets category and order
    for m_data in markets:
        m = next((m for m in db["markets"] if m["id"] == m_data["id"]), None)
        if m:
            m["categoryId"] = m_data.get("categoryId")
            m["order"] = m_data.get("order", 0)
            
    save_db(db)
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN – JOURNAL DES CRÉDITS
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/admin/grants-log")
@admin_required
def admin_grants_log():
    """Accessible uniquement par le super-admin (id='admin')."""
    if session["user_id"] != "admin":
        return jsonify({"error": "Réservé au super-admin"}), 403
    db = load_db()
    return jsonify(db.get("admin_grants_log", []))


# ──────────────────────────────────────────────────────────────────────────────
# DEMANDES DE CHANGEMENT DE PSEUDONYME
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/profile/request-name-change", methods=["POST"])
@login_required
def request_name_change():
    data = request.get_json()
    new_name = (data.get("newName") or "").strip()
    if not new_name or len(new_name) < 2:
        return jsonify({"error": "Le pseudonyme doit faire au moins 2 caractères"}), 400
    db = load_db()
    user = db["users"].get(session["user_id"])
    # Vérifier qu'il n'y a pas déjà une demande en attente
    pending = next((r for r in db["name_change_requests"]
                    if r["userId"] == user["id"] and r["status"] == "pending"), None)
    if pending:
        return jsonify({"error": "Vous avez déjà une demande en attente"}), 400
    req = {
        "id": "nc" + secrets.token_hex(6),
        "userId": user["id"],
        "oldName": user["name"],
        "newName": new_name,
        "status": "pending",
        "createdAt": datetime.now(timezone.utc).isoformat()
    }
    db["name_change_requests"].insert(0, req)
    save_db(db)
    return jsonify({"ok": True})


@app.route("/api/admin/name-changes")
@admin_required
def admin_get_name_changes():
    db = load_db()
    return jsonify([r for r in db["name_change_requests"] if r["status"] == "pending"])


@app.route("/api/admin/name-change/<req_id>/approve", methods=["POST"])
@admin_required
def admin_approve_name_change(req_id):
    db = load_db()
    req = next((r for r in db["name_change_requests"] if r["id"] == req_id), None)
    if not req:
        return jsonify({"error": "Demande introuvable"}), 404
    user = db["users"].get(req["userId"])
    if user:
        user["name"] = req["newName"]
        add_tx(user, f"Pseudonyme changé en '{req['newName']}'", 0)
    req["status"] = "approved"
    save_db(db)
    return jsonify({"ok": True})


@app.route("/api/admin/name-change/<req_id>/reject", methods=["POST"])
@admin_required
def admin_reject_name_change(req_id):
    db = load_db()
    req = next((r for r in db["name_change_requests"] if r["id"] == req_id), None)
    if not req:
        return jsonify({"error": "Demande introuvable"}), 404
    req["status"] = "rejected"
    save_db(db)
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"[OK] PolyBoquette demarre sur http://localhost:{port}")
    print(f"   DB : {DB_PATH}")
    app.run(host="0.0.0.0", port=port, debug=debug)
