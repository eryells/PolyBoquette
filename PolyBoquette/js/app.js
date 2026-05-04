
const state = {
    version: 5,
    useApi: false, // Detecté auto au lancement
    currentUser: null,
    theme: 'dark',
    data: {
        users: {
            admin: { id: 'admin', username: 'admin', password: '123', name: 'ADMIN', role: 'admin', status: 'active', points: 1000, buque: 'BDE', nums: '1', proms: 'Me221' },
            user1: { id: 'user1', username: 'jean', password: '123', name: 'Jean Dupont', role: 'user', status: 'active', points: 1000, buque: 'Bab', nums: '123', proms: 'An211' },
        },
        markets: [],
        proposals: [] // <-- NOUVEAU
    },
    currentView: 'dashboard',
    currentMarketId: null,
    selectedOptionId: null,
    chartHidden: false,
    leaderboard: [],
    canClaim: false,
    dashTab: 'markets'   // 'markets' | 'leaderboard'
};

const PALETTE = ['#22c55e', '#ef4444', '#3b82f6', '#d946ef', '#f97316', '#eab308', '#06b6d4'];

function getAdjustedProbabilities(market, betToExclude) {
    let totalShares = market.options.reduce((sum, opt) => sum + opt.shares, 0);
    if(betToExclude) totalShares -= betToExclude.amount;
    
    const probs = {};
    if (totalShares <= 0) {
        const defaultProb = Math.round(100 / market.options.length);
        market.options.forEach(opt => probs[opt.id] = defaultProb);
    } else {
        market.options.forEach(opt => {
            const adjShares = (betToExclude && opt.id === betToExclude.optId) 
                ? Math.max(0, opt.shares - betToExclude.amount) 
                : opt.shares;
            probs[opt.id] = Math.round((adjShares / totalShares) * 100);
        });
    }
    return probs;
}

function getProbabilities(market) {
    return getAdjustedProbabilities(market, null);
}

const ui = {
    showToast: (msg, type = 'success') => {
        const container = document.getElementById('toast-container');
        if(!container) return;
        const t = document.createElement('div');
        const icon = type === 'success' ? 'fa-check' : 'fa-triangle-exclamation';
        t.className = `toast toast-${type}`;
        t.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${msg}</span>`;
        container.appendChild(t);
        setTimeout(() => {
            t.style.animation = 'fadeOut 0.3s ease forwards';
            setTimeout(() => t.remove(), 300);
        }, 3000);
    },
    showModal: (title, content, onConfirm, confirmText = "Valider") => {
        const c = document.getElementById('modal-container');
        if(!c) return;
        c.innerHTML = `
            <div class="modal-overlay" onclick="if(event.target.className === 'modal-overlay') ui.closeModal(true)">
                <div class="modal-content">
                    <h2 style="font-size: 1.25rem;">${title}</h2>
                    <div style="margin: 1.5rem 0;">${content}</div>
                    <div class="modal-footer">
                        <button class="btn-outline" onclick="ui.closeModal(true)">Annuler</button>
                        <button class="btn-primary" id="modalConfirmBtn">${confirmText}</button>
                    </div>
                </div>
            </div>
        `;
        document.getElementById('modalConfirmBtn').onclick = () => { onConfirm(); };
    },
    closeModal: (force = false) => {
        if (force) {
            document.getElementById('modal-container').innerHTML = '';
        }
    }
};

// --- INITIALISATION API / LOCAL ---
async function init() {
    // Theme setup
    const savedTheme = localStorage.getItem('theme') || 'dark';
    state.theme = savedTheme;
    document.documentElement.setAttribute('data-theme', state.theme);
    updateThemeIcon();

    // Chart preference
    state.chartHidden = localStorage.getItem('chartHidden') === '1';

    try {
        // Tente de contacter le backend Flask
        const res = await fetch('/api/auth/me');
        if (res.ok) {
            state.useApi = true;
            console.log("🔥 Backend Flask détecté ! Mode Serveur Activé.");
            const authData = await res.json();
            if (authData.user) state.currentUser = authData.user;
            await refreshServerData();
        } else {
            throw new Error("API not ready");
        }
    } catch (e) {
        console.log("💾 Pas de Backend détecté. Mode LocalStorage Activé.");
        state.useApi = false;
        initLocalData();
    }
    
    updateNavbar();
    app.navigate('dashboard');
}

function initLocalData() {
    try {
        const saved = localStorage.getItem('polyboquette_data');
        if (saved) {
            const parsed = JSON.parse(saved);
            if (!parsed.proposals) parsed.proposals = []; // migration v5
            Object.values(parsed.users).forEach(u => {
                if(!u.transactions) u.transactions = [];
            });
            state.data = parsed;
        } else {
            saveDataLocal();
        }
    } catch(e) {
        saveDataLocal();
    }
    const session = localStorage.getItem('polyboquette_session');
    if (session && state.data.users[session] && state.data.users[session].status === 'active') {
        state.currentUser = state.data.users[session];
    }
}

function saveDataLocal() {
    if(!state.useApi) {
        localStorage.setItem('polyboquette_data', JSON.stringify(state.data));
    }
}

function addLocalTx(user, desc, amount) {
    if(!user.transactions) user.transactions = [];
    user.transactions.unshift({
        time: new Date().toISOString(),
        desc: desc,
        amount: amount
    });
    if(user.transactions.length > 50) user.transactions.pop();
}

async function refreshServerData() {
    if(!state.useApi) return;
    const marketsRes = state.currentUser ? fetch('/api/markets').catch(()=>null) : Promise.resolve(null);
    const [mRes, pRes, lbRes] = await Promise.all([
        marketsRes,
        state.currentUser ? fetch('/api/proposals').catch(()=>null) : Promise.resolve(null),
        fetch('/api/leaderboard').catch(()=>null)
    ]);
    if(mRes && mRes.ok) state.data.markets = await mRes.json();
    if(pRes && pRes.ok) state.data.proposals = await pRes.json();
    if(lbRes && lbRes.ok) state.leaderboard = await lbRes.json();

    if(state.currentUser?.role === 'admin') {
        const [uRes, ncRes] = await Promise.all([
            fetch('/api/admin/users').catch(()=>null),
            fetch('/api/admin/name-changes').catch(()=>null)
        ]);
        if(uRes && uRes.ok) {
            const users = await uRes.json();
            state.data.users = {};
            users.forEach(u => state.data.users[u.id] = u);
        }
        if(ncRes && ncRes.ok) state.data.nameChangeRequests = await ncRes.json();
    } else if (state.currentUser) {
        state.data.users = {};
        state.data.users[state.currentUser.id] = state.currentUser;
    }

    // Vérifier si le bonus quotidien est disponible
    if (state.currentUser) {
        const today = new Date().toISOString().slice(0, 10);
        const lastClaim = state.currentUser.lastClaim || '';
        state.canClaim = lastClaim !== today;
    }
}

async function apiCall(method, url, data = null) {
    if(!state.useApi) return null;
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if(data) opts.body = JSON.stringify(data);
    const res = await fetch(url, opts);
    if(!res.ok) {
        const err = await res.json().catch(()=>({error: "Erreur serveur"}));
        throw new Error(err.error || "Erreur serveur");
    }
    return res.json();
}

// --- LOGIQUE METIER ---
const app = {
    toggleTheme: () => {
        state.theme = state.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', state.theme);
        localStorage.setItem('theme', state.theme);
        updateThemeIcon();
        if (state.currentView === 'market') app.navigate('market', state.currentMarketId);
    },
    
    logout: async () => {
        if(state.useApi) {
            await apiCall('POST', '/api/auth/logout');
        }
        state.currentUser = null;
        localStorage.removeItem('polyboquette_session');
        updateNavbar();
        app.navigate('dashboard');
    },

    navigate: async (view, id = null) => {
        const isNewMarket = (view === 'market' && state.currentMarketId !== id);
        state.currentView = view;
        state.currentMarketId = id;
        
        const container = document.getElementById('app-container');
        container.innerHTML = '<div style="text-align:center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>'; 
        
        if(state.useApi) await refreshServerData();

        if (view === 'dashboard') container.innerHTML = renderDashboard();
        else if (view === 'market') {
            const market = state.data.markets.find(m => m.id === id);
            if(!market) return container.innerHTML = '<p>Introuvable</p>';
            if (isNewMarket) {
                state.selectedOptionId = market.options[0].id;
            }
            container.innerHTML = renderMarket(id);
            setTimeout(() => initChart(id), 10);
        }
        else if (view === 'admin') container.innerHTML = renderAdmin();
        else if (view === 'login') container.innerHTML = renderLogin();
        else if (view === 'register') container.innerHTML = renderRegister();
        else if (view === 'proposals') container.innerHTML = renderProposals();
        else if (view === 'profile') container.innerHTML = renderProfile();
    },

    selectOption: (optId) => {
        state.selectedOptionId = optId;
        app.navigate('market', state.currentMarketId); 
    },

    updateGainEstimate: () => {
        const amount = parseInt(document.getElementById('betAmount').value);
        const estEl = document.getElementById('gainEstimateValue');
        if (isNaN(amount) || amount <= 0) {
            if(estEl) estEl.innerHTML = `~ 0 pts`;
            return;
        }
        
        const market = state.data.markets.find(m => m.id === state.currentMarketId);
        const probs = getProbabilities(market);
        const prob = probs[state.selectedOptionId];
        
        if (prob === 0) {
            if(estEl) estEl.innerHTML = `Potentiel élevé (0%)`;
        } else {
            const multiplier = 100 / prob;
            const payout = Math.floor(amount * multiplier);
            if(estEl) estEl.innerHTML = `~ ${payout} pts (x${multiplier.toFixed(2)})`;
        }
    },

    placeBet: async () => {
        if (!state.currentUser) {
            ui.showToast("Veuillez vous connecter pour miser !", 'error');
            return app.navigate('login');
        }

        const amount = parseInt(document.getElementById('betAmount').value);
        if (isNaN(amount) || amount <= 0) return ui.showToast("Montant invalide", 'error');
        if (state.currentUser.points < amount) return ui.showToast("Solde insuffisant !", 'error');

        const market = state.data.markets.find(m => m.id === state.currentMarketId);
        if (market.status !== 'open') return ui.showToast("Ce pari n'accepte plus de transactions !", 'error');

        const optId = state.selectedOptionId;

        if (state.useApi) {
            try {
                const res = await apiCall('POST', `/api/markets/${market.id}/bet`, { optId, amount });
                if (res.user) state.currentUser = res.user;
                ui.showToast("Mise effectuée avec succès !");
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            state.currentUser.points -= amount;
            market.volume += amount;
            const option = market.options.find(o => o.id === optId);
            option.shares += amount;
            const probs = getProbabilities(market);
            const now_iso = new Date().toISOString();
            // Agrégation locale : fusionner avec position existante
            const existing = market.bets.find(b => b.userId === state.currentUser.id && b.optId === optId);
            if (existing) {
                const oldAmt = existing.amount;
                const newTotal = oldAmt + amount;
                existing.buyProb = Math.round((existing.buyProb * oldAmt + probs[optId] * amount) / newTotal);
                existing.amount = newTotal;
                existing.time = now_iso;
            } else {
                market.bets.push({
                    id: 'b' + Date.now() + Math.floor(Math.random()*100),
                    userId: state.currentUser.id,
                    optId, amount,
                    buyProb: probs[optId],
                    time: now_iso
                });
            }
            market.history.push({ time: now_iso, ...probs });
            addLocalTx(state.currentUser, `Mise dans '${market.title}'`, -amount);
            state.data.users[state.currentUser.id].points = state.currentUser.points;
            saveDataLocal();
            ui.showToast("Mise effectuée avec succès !");
        }

        updateNavbar();
        app.navigate('market', market.id);
    },
    
    cashOutBet: async (marketId, betId, partialAmount) => {
        const market = state.data.markets.find(m => m.id === marketId);
        if (market.status !== 'open') return ui.showToast("Le marché ne permet plus de revente !", 'error');

        if (state.useApi) {
            try {
                const body = partialAmount ? { amount: partialAmount } : {};
                const res = await apiCall('POST', `/api/markets/${marketId}/cashout/${betId}`, body);
                if (res.user) state.currentUser = res.user;
                ui.showToast(`Revente effectuée : +${res.refund} points.`);
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            const betIndex = market.bets.findIndex(b => b.id === betId);
            const bet = market.bets[betIndex];
            if(bet.userId !== state.currentUser?.id) return;

            const sellAmt = partialAmount ? Math.min(partialAmount, bet.amount) : bet.amount;
            const proxyBet = { amount: sellAmt, optId: bet.optId };
            const adjustedProbs = getAdjustedProbabilities(market, proxyBet);
            const currentProb = adjustedProbs[bet.optId] || 1;
            const rawValue = sellAmt * (currentProb / (bet.buyProb || 1));
            let refund = Math.max(1, Math.floor(rawValue * 0.97));

            state.currentUser.points += refund;
            market.volume = Math.max(0, market.volume - sellAmt);
            const opt = market.options.find(o => o.id === bet.optId);
            opt.shares = Math.max(0, opt.shares - sellAmt);

            const newProbs = getProbabilities(market);
            market.history.push({ time: new Date().toISOString(), ...newProbs });

            if (sellAmt >= bet.amount) {
                market.bets.splice(betIndex, 1);
            } else {
                bet.amount -= sellAmt;
            }

            addLocalTx(state.currentUser, `Revente dans '${market.title}'`, refund);
            state.data.users[state.currentUser.id].points = state.currentUser.points;
            saveDataLocal();
            ui.showToast(`Revente effectuée : +${refund} points.`);
        }

        updateNavbar();
        app.navigate('market', marketId);
    },

    // AUTH
    doLogin: async () => {
        const userIn = document.getElementById('logUsername').value;
        const passIn = document.getElementById('logPass').value;
        
        if (state.useApi) {
            try {
                const res = await apiCall('POST', '/api/auth/login', { username: userIn, password: passIn });
                state.currentUser = res.user;
                ui.showToast("Connexion réussie");
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            const user = Object.values(state.data.users).find(u => u.username === userIn && u.password === passIn);
            if (!user) return ui.showToast("Identifiants incorrects.", 'error');
            if (user.status === 'pending') return ui.showToast("Compte en attente.", 'error');
            if (user.status === 'rejected') return ui.showToast("Compte rejeté.", 'error');
            state.currentUser = user;
            localStorage.setItem('polyboquette_session', user.id);
        }
        
        updateNavbar();
        app.navigate('dashboard');
    },

    doRegister: async () => {
        const data = {
            username: document.getElementById('regUsername').value,
            password: document.getElementById('regPass').value,
            name: document.getElementById('regName').value,
            buque: document.getElementById('regBuque').value,
            nums: document.getElementById('regNums').value,
            proms: document.getElementById('regProms').value
        };
        
        if(!data.username || !data.password || !data.name) return ui.showToast("Nom, identifiant et pass requis.", "error");
        
        if (state.useApi) {
            try {
                await apiCall('POST', '/api/auth/register', data);
                ui.showToast("Inscription réussie ! Validation admin requise.");
                app.navigate('login');
            } catch(e) {
                ui.showToast(e.message, 'error');
            }
        } else {
            if (Object.values(state.data.users).find(usr => usr.username === data.username)) return ui.showToast("L'identifiant est déjà pris.", "error");
            const newId = 'u' + Date.now();
            state.data.users[newId] = {
                id: newId, role: 'user', status: 'pending', points: 100, ...data
            };
            saveDataLocal();
            ui.showToast("Inscription réussie ! Validation admin requise.");
            app.navigate('login');
        }
    },

    // PROPOSALS
    submitProposal: async () => {
        const title = document.getElementById('propTitle').value;
        const choicesStr = document.getElementById('propChoices').value;
        const imgIn = document.getElementById('propImage').value.trim();
        const choices = choicesStr.split(',').map(s => s.trim()).filter(s => s.length > 0);
        
        if (!title) return ui.showToast("Le titre est requis.", "error");
        if (choices.length < 2) return ui.showToast("Veuillez saisir au moins 2 options valides.", "error");

        if (state.useApi) {
            try {
                await apiCall('POST', '/api/proposals', { title, choices, image: imgIn });
                ui.showToast("Proposition envoyée au BDE !");
                app.navigate('proposals');
            } catch(e) {
                ui.showToast(e.message, 'error');
            }
        } else {
            const p = {
                id: 'p' + Date.now(),
                authorId: state.currentUser.id,
                authorName: state.currentUser.name,
                title: title,
                choices: choices,
                image: imgIn,
                status: 'pending',
                adminNote: '',
                createdAt: new Date().toISOString()
            };
            state.data.proposals.push(p);
            saveDataLocal();
            ui.showToast("Proposition envoyée au BDE !");
            app.navigate('proposals');
        }
    },

    // ADMIN
    approveUser: async (id) => {
        if(state.useApi) {
            await apiCall('POST', `/api/admin/users/${id}/approve`);
        } else {
            state.data.users[id].status = 'active';
            saveDataLocal();
        }
        ui.showToast("Utilisateur approuvé !");
        app.navigate('admin');
    },
    
    rejectUser: async (id) => {
        if(state.useApi) {
            await apiCall('POST', `/api/admin/users/${id}/reject`);
        } else {
            state.data.users[id].status = 'rejected';
            saveDataLocal();
        }
        ui.showToast("Utilisateur rejeté.");
        app.navigate('admin');
    },

    grantPoints: (userId) => {
        ui.showModal(
            "<i class='fa-solid fa-coins'></i> Modifier les points",
            `
            <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:1rem;">Entrez un montant positif pour créditer, ou négatif pour débiter (le solde ne peut pas passer sous 0).</p>
            <label style="display:block; margin-bottom:0.5rem; font-weight:500;">Montant de points :</label>
            <input type="number" id="modalGrantPoints" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);" placeholder="ex: 500 ou -200">
            `,
            async () => {
                const amount = parseInt(document.getElementById('modalGrantPoints').value);
                if (isNaN(amount) || amount === 0) return ui.showToast("Montant invalide", "error");
                
                if(state.useApi) {
                    await apiCall('POST', `/api/admin/users/${userId}/grant`, {amount});
                } else {
                    const user = state.data.users[userId];
                    user.points = Math.max(0, user.points + amount);
                    addLocalTx(user, amount > 0 ? `Crédit admin : +${amount} pts` : `Débit admin : ${amount} pts`, amount);
                    if(userId === state.currentUser.id) state.currentUser.points = user.points;
                    saveDataLocal();
                }
                updateNavbar();
                ui.closeModal(true);
                app.navigate('admin');
                ui.showToast((amount > 0 ? '+' : '') + amount + " points appliqués.");
            },
            "Appliquer"
        );
    },

    viewUserHistory: async (userId, userName) => {
        let txs = [];
        if (state.useApi) {
            try {
                txs = await apiCall('GET', `/api/users/${userId}/transactions`);
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            txs = state.data.users[userId]?.transactions || [];
        }
        const rows = txs.length === 0
            ? '<p style="color:var(--text-secondary);text-align:center;">Aucune transaction.</p>'
            : txs.map(tx => formatTxRow(tx)).join('');
        ui.showModal(
            `<i class='fa-solid fa-clock-rotate-left'></i> Historique de ${userName}`,
            `<div style="max-height:400px; overflow-y:auto;">${rows}</div>`,
            () => {},
            "Fermer"
        );
    },

    toggleAdmin: async (userId) => {
        if(state.currentUser.id !== 'admin') return;
        if(state.useApi) {
            await apiCall('POST', `/api/admin/users/${userId}/toggle-role`);
        } else {
            const user = state.data.users[userId];
            user.role = user.role === 'admin' ? 'user' : 'admin';
            saveDataLocal();
        }
        ui.showToast("Rôle mis à jour !");
        app.navigate('admin');
    },

    createMarketDirect: () => {
        ui.showModal(
            "<i class='fa-solid fa-square-plus'></i> Créer un marché officiel",
            `
            <label style="display:block; margin-bottom:0.5rem; font-weight:500;">Titre du sondage / pari</label>
            <input type="text" id="modalMarketTitle" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:1rem;" placeholder="Ex: Qui gagnera l'élection ?">
            
            <label style="display:block; margin-bottom:0.5rem; font-weight:500;">Choix possibles (séparés par des virgules)</label>
            <input type="text" id="modalMarketChoices" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:1rem;" placeholder="Ex: Option A, Option B">

            <label style="display:block; margin-bottom:0.5rem; font-weight:500;">Image d'illustration (URL)</label>
            <input type="text" id="modalMarketImage" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);" placeholder="https:// (optionnel)">
            `,
            async () => {
                const title = document.getElementById('modalMarketTitle').value;
                const choicesStr = document.getElementById('modalMarketChoices').value;
                const imgIn = document.getElementById('modalMarketImage').value.trim();
                const choices = choicesStr.split(',').map(s => s.trim()).filter(s => s.length > 0);
                
                if (!title) return ui.showToast("Le titre est requis.", "error");
                if (choices.length < 2) return ui.showToast("Veuillez saisir au moins 2 options.", "error");

                if (state.useApi) {
                    try {
                        await apiCall('POST', '/api/admin/markets', { title, choices, image: imgIn });
                        ui.showToast("Marché créé !");
                    } catch(e) {
                        return ui.showToast(e.message, 'error');
                    }
                } else {
                    const options = choices.map((c, i) => ({
                        id: 'o' + (i+1), label: c, shares: 0, color: PALETTE[i % PALETTE.length]
                    }));
                    const initialProbs = {};
                    options.forEach(o => initialProbs[o.id] = Math.round(100/choices.length));

                    state.data.markets.push({
                        id: 'm' + Date.now(), title: title, 
                        image: imgIn || 'https://images.unsplash.com/photo-1550565118-3a14e8d0386f?auto=format&fit=crop&w=150&q=80',
                        volume: 0, status: 'open', resolvedWinner: null, bets: [], options: options,
                        history: [{ time: 'Début', ...initialProbs }]
                    });
                    saveDataLocal();
                    ui.showToast("Marché créé !");
                }
                ui.closeModal(true);
                app.navigate('admin');
            },
            "Mettre en ligne"
        );
    },

    approveProposal: async (propId) => {
        if(state.useApi) {
            try {
                await apiCall('POST', `/api/proposals/${propId}/approve`);
                ui.showToast("Proposition transformée en marché !");
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            const p = state.data.proposals.find(x => x.id === propId);
            p.status = 'approved';
            
            const options = p.choices.map((c, i) => ({
                id: 'o' + (i+1), label: c, shares: 0, color: PALETTE[i % PALETTE.length]
            }));
            const initialProbs = {};
            options.forEach(o => initialProbs[o.id] = Math.round(100/p.choices.length));

            state.data.markets.push({
                id: 'm' + Date.now(), title: p.title, 
                image: p.image || 'https://images.unsplash.com/photo-1550565118-3a14e8d0386f?auto=format&fit=crop&w=150&q=80',
                volume: 0, status: 'open', resolvedWinner: null, bets: [], options: options,
                history: [{ time: 'Début', ...initialProbs }]
            });
            saveDataLocal();
            ui.showToast("Proposition transformée en marché !");
        }
        app.navigate('admin');
    },

    rejectProposal: (propId) => {
        ui.showModal(
            "<i class='fa-solid fa-ban'></i> Rejeter la proposition",
            `
            <label style="display:block; margin-bottom:0.5rem; font-weight:500;">Raison du rejet (visible par l'utilisateur) :</label>
            <input type="text" id="modalRejectNote" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);" placeholder="Ex: Sujet déjà existant...">
            `,
            async () => {
                const note = document.getElementById('modalRejectNote').value;
                if(state.useApi) {
                    await apiCall('POST', `/api/proposals/${propId}/reject`, {note});
                } else {
                    const p = state.data.proposals.find(x => x.id === propId);
                    p.status = 'rejected';
                    p.adminNote = note;
                    saveDataLocal();
                }
                ui.closeModal(true);
                app.navigate('admin');
                ui.showToast("Proposition rejetée.");
            },
            "Confirmer le rejet"
        );
    },

    executeResolution: async (marketId, winnerId) => {
        if(state.useApi) {
            try {
                await apiCall('POST', `/api/admin/markets/${marketId}/resolve`, {winnerId});
                ui.showToast("Marché clôturé !");
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            const market = state.data.markets.find(m => m.id === marketId);
            market.status = 'resolved';
            market.resolvedWinner = winnerId;

            if (winnerId === 'cancelled') {
                market.bets.forEach(b => {
                    if (state.data.users[b.userId]) {
                        state.data.users[b.userId].points += b.amount;
                        addLocalTx(state.data.users[b.userId], `Remboursement annulation '${market.title}'`, b.amount);
                    }
                });
            } else {
                // Pari Mutuel pur sur les VRAIES mises uniquement
                const realTotalPool = market.bets.reduce((s, b) => s + b.amount, 0);
                const realWinningPool = market.bets.filter(b => b.optId === winnerId).reduce((s, b) => s + b.amount, 0);

                if (realWinningPool === 0) {
                    market.bets.forEach(b => {
                        if (state.data.users[b.userId]) {
                            state.data.users[b.userId].points += b.amount;
                            addLocalTx(state.data.users[b.userId], `Remboursement (aucun gagnant) '${market.title}'`, b.amount);
                        }
                    });
                } else {
                    market.bets.forEach(b => {
                        if (state.data.users[b.userId]) {
                            if (b.optId === winnerId) {
                                const payout = Math.max(0, Math.floor((b.amount / realWinningPool) * realTotalPool));
                                state.data.users[b.userId].points += payout;
                                addLocalTx(state.data.users[b.userId], `Gain '${market.title}'`, payout);
                            } else {
                                addLocalTx(state.data.users[b.userId], `Pari perdu '${market.title}'`, 0);
                            }
                        }
                    });
                }
            }
            saveDataLocal();
            ui.showToast("Marché clôturé !");
        }
        ui.closeModal(true);
        app.navigate('admin');
    },

    resolveMarketPrompt: (marketId) => {
        const market = state.data.markets.find(m => m.id === marketId);
        let opts = `<select id="modalResolveWinner" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:1rem;">
            <option value="cancelled">-- ANNULER (Remboursement Intégral) --</option>`;
        market.options.forEach(o => { opts += `<option value="${o.id}">Déclarer Vainqueur : ${o.label}</option>` });
        opts += `</select>`;

        ui.showModal(
            "<i class='fa-solid fa-gavel'></i> Clôturer le marché",
            `<p style="margin-bottom: 1rem">Veuillez désigner l'issue finale pour <b>"${market.title}"</b>.</p>${opts}`,
            () => {
                const winnerId = document.getElementById('modalResolveWinner').value;
                app.executeResolution(marketId, winnerId);
            },
            "Confirmer la clôture"
        );
    },

    togglePause: async (marketId) => {
        if(state.useApi) {
            await apiCall('POST', `/api/admin/markets/${marketId}/toggle-pause`);
        } else {
            const market = state.data.markets.find(m => m.id === marketId);
            market.status = market.status === 'paused' ? 'open' : 'paused';
            saveDataLocal();
        }
        app.navigate('admin');
    },

    deleteMarket: async (marketId) => {
        if (!confirm("Voulez-vous vraiment supprimer ce marché définitivement ?")) return;
        if(state.useApi) {
            try {
                await apiCall('DELETE', `/api/admin/markets/${marketId}`);
                ui.showToast("Marché supprimé.");
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            state.data.markets = state.data.markets.filter(m => m.id !== marketId);
            saveDataLocal();
            ui.showToast("Marché supprimé.");
        }
        app.navigate('admin');
    },

    changePassword: async () => {
        const oldPass = document.getElementById('oldPass')?.value;
        const newPass = document.getElementById('newPass')?.value;
        const newPass2 = document.getElementById('newPass2')?.value;

        if (!oldPass || !newPass || !newPass2) return ui.showToast('Veuillez remplir tous les champs.', 'error');
        if (newPass !== newPass2) return ui.showToast('Les nouveaux mots de passe ne correspondent pas.', 'error');
        if (newPass.length < 3) return ui.showToast('Le nouveau mot de passe est trop court.', 'error');

        if (state.useApi) {
            try {
                await apiCall('POST', '/api/auth/change-password', { oldPassword: oldPass, newPassword: newPass });
                ui.showToast('Mot de passe chang\u00e9 avec succ\u00e8s !');
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            if (state.currentUser.password !== oldPass) return ui.showToast('Ancien mot de passe incorrect.', 'error');
            state.currentUser.password = newPass;
            state.data.users[state.currentUser.id].password = newPass;
            saveDataLocal();
            ui.showToast('Mot de passe chang\u00e9 avec succ\u00e8s !');
        }
        document.getElementById('oldPass').value = '';
        document.getElementById('newPass').value = '';
        document.getElementById('newPass2').value = '';
    },

    toggleChart: () => {
        state.chartHidden = !state.chartHidden;
        localStorage.setItem('chartHidden', state.chartHidden ? '1' : '0');
        const wrapper = document.getElementById('chartWrapper');
        const btn = document.getElementById('chartToggleBtn');
        if (wrapper) wrapper.style.display = state.chartHidden ? 'none' : '';
        if (btn) btn.innerHTML = state.chartHidden
            ? '<i class="fa-solid fa-chart-line"></i> Afficher le graphe'
            : '<i class="fa-solid fa-eye-slash"></i> Masquer le graphe';
        if (!state.chartHidden) setTimeout(() => initChart(state.currentMarketId), 10);
    },

    deleteUser: async (userId, userName) => {
        if (!confirm(`Supprimer définitivement le compte de "${userName}" ? Cette action est irréversible.`)) return;
        if (state.useApi) {
            try {
                await apiCall('DELETE', `/api/admin/users/${userId}`);
                ui.showToast('Compte supprimé.');
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            delete state.data.users[userId];
            saveDataLocal();
            ui.showToast('Compte supprimé.');
        }
        app.navigate('admin');
    },

    claimDaily: async () => {
        if (state.useApi) {
            try {
                const res = await apiCall('POST', '/api/auth/daily-claim');
                state.currentUser = res.user;
                ui.showToast('\uD83C\uDF81 +5 points r\u00e9cup\u00e9r\u00e9s ! Revenez demain.');
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            const today = new Date().toISOString().slice(0, 10);
            if (state.currentUser.lastClaim === today) {
                return ui.showToast('Bonus d\u00e9j\u00e0 r\u00e9cup\u00e9r\u00e9 aujourd\u2019hui !', 'error');
            }
            state.currentUser.lastClaim = today;
            state.currentUser.points += 5;
            state.data.users[state.currentUser.id].lastClaim = today;
            state.data.users[state.currentUser.id].points += 5;
            addLocalTx(state.currentUser, 'Bonus quotidien', 5);
            saveDataLocal();
            ui.showToast('\uD83C\uDF81 +5 points r\u00e9cup\u00e9r\u00e9s ! Revenez demain.');
        }
        updateNavbar();
        app.navigate('dashboard');
    },

    switchTab: (tab) => {
        state.dashTab = tab;
        const container = document.getElementById('app-container');
        if (container) container.innerHTML = renderDashboard();
    },

    requestNameChange: () => {
        const pending = state.data.nameChangeRequests?.some(r => r.status === 'pending');
        if (pending) return ui.showToast('Vous avez déjà une demande en attente.', 'error');
        ui.showModal(
            "<i class='fa-solid fa-pen'></i> Changer mon nom affiché",
            `<p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:1rem;">Ce changement doit être validé par un admin. Votre nom actuel : <strong>${state.currentUser.name}</strong></p>
            <label style="display:block; margin-bottom:0.5rem; font-weight:500;">Nouveau nom affiché :</label>
            <input type="text" id="modalNewName" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);" placeholder="Ex: Jean-Pierre">`,
            async () => {
                const newName = document.getElementById('modalNewName').value.trim();
                if (!newName || newName.length < 2) return ui.showToast('Nom trop court.', 'error');
                if (state.useApi) {
                    try {
                        await apiCall('POST', '/api/profile/request-name-change', { newName });
                        ui.showToast('Demande envoyée ! Un admin la traitera bientôt.');
                    } catch(e) { return ui.showToast(e.message, 'error'); }
                } else {
                    ui.showToast('Demande envoyée ! (Mode local : changement immédiat)');
                    state.currentUser.name = newName;
                    state.data.users[state.currentUser.id].name = newName;
                    saveDataLocal();
                    updateNavbar();
                }
                ui.closeModal(true);
                app.navigate('profile');
            },
            'Envoyer la demande'
        );
    },

    approveNameChange: async (reqId) => {
        if (state.useApi) {
            try { await apiCall('POST', `/api/admin/name-change/${reqId}/approve`); }
            catch(e) { return ui.showToast(e.message, 'error'); }
        }
        ui.showToast('Pseudonyme approuvé !');
        app.navigate('admin');
    },

    rejectNameChange: async (reqId) => {
        if (state.useApi) {
            try { await apiCall('POST', `/api/admin/name-change/${reqId}/reject`); }
            catch(e) { return ui.showToast(e.message, 'error'); }
        }
        ui.showToast('Demande rejetée.');
        app.navigate('admin');
    },

    viewGrantsLog: async () => {
        let logs = [];
        if (state.useApi) {
            try { logs = await apiCall('GET', '/api/admin/grants-log'); }
            catch(e) { return ui.showToast(e.message, 'error'); }
        }
        if (logs.length === 0) {
            return ui.showModal('<i class="fa-solid fa-list"></i> Journal des crédits', '<p style="color:var(--text-secondary)">Aucun crédit admin enregistré.</p>', () => {}, 'Fermer');
        }
        const rows = logs.map(l => {
            const d = new Date(l.time);
            const ds = d.toLocaleDateString('fr-FR') + ' ' + d.toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
            const col = l.amount > 0 ? 'var(--yes-color)' : 'var(--no-color)';
            return `<div class="user-row" style="flex-direction:column; align-items:flex-start; gap:0.2rem;">
                <div style="display:flex; justify-content:space-between; width:100%">
                    <span><strong>${l.adminName}</strong> → <strong>${l.targetName}</strong></span>
                    <span style="color:${col}; font-weight:700">${l.amount > 0 ? '+' : ''}${l.amount} pts</span>
                </div>
                <div style="font-size:0.78rem; color:var(--text-secondary)">${ds}</div>
            </div>`;
        }).join('');
        ui.showModal('<i class="fa-solid fa-list"></i> Journal des crédits admin',
            `<div style="max-height:450px; overflow-y:auto;">${rows}</div>`, () => {}, 'Fermer');
    }
};

// --- RENDERING ---
function updateThemeIcon() {
    const icon = document.querySelector('#themeToggle i');
    if (state.theme === 'dark') icon.className = 'fa-solid fa-sun';
    else icon.className = 'fa-solid fa-moon';
}

function updateNavbar() {
    const userPill = document.getElementById('userPill');
    const authActions = document.getElementById('authActions');
    const logoutBtn = document.getElementById('logoutBtn');
    
    // Ajout bouton Proposition
    let propBtn = document.getElementById('navPropBtn');
    if(state.currentUser && !propBtn) {
        propBtn = document.createElement('button');
        propBtn.id = 'navPropBtn';
        propBtn.className = 'btn-outline';
        propBtn.innerHTML = '<i class="fa-solid fa-lightbulb"></i> Proposer un pari';
        propBtn.onclick = () => app.navigate('proposals');
        document.querySelector('.nav-actions').insertBefore(propBtn, document.getElementById('authActions'));
    } else if (!state.currentUser && propBtn) {
        propBtn.remove();
    }

    if (state.currentUser) {
        document.getElementById('userName').textContent = state.currentUser.name;
        document.getElementById('userPoints').innerHTML = `<i class="fa-solid fa-coins"></i> ${Math.floor(state.currentUser.points)}`;
        
        userPill.classList.remove('hidden');
        userPill.style.cursor = 'pointer';
        userPill.onclick = () => app.navigate('profile');
        
        logoutBtn.classList.remove('hidden');
        authActions.classList.add('hidden');
        
        let adminBtn = document.getElementById('adminBtn');
        if (state.currentUser.role === 'admin' && !adminBtn) {
            const btn = document.createElement('button');
            btn.id = 'adminBtn';
            btn.className = 'btn-primary';
            btn.innerHTML = '<i class="fa-solid fa-shield-halved"></i> Admin';
            btn.onclick = () => app.navigate('admin');
            document.querySelector('.nav-actions').insertBefore(btn, document.getElementById('authActions'));
        }
    } else {
        userPill.classList.add('hidden');
        logoutBtn.classList.add('hidden');
        authActions.classList.remove('hidden');
        let adminBtn = document.getElementById('adminBtn');
        if (adminBtn) adminBtn.remove();
    }
}

function renderLogin() {
    return `
        <div style="max-width: 400px; margin: 4rem auto; background: var(--bg-card); padding: 2rem; border-radius: var(--radius-lg); border: 1px solid var(--border-color);">
            <h2 style="margin-bottom: 1.5rem; text-align: center;">Connexion</h2>
            <div class="trade-input-group">
                <label>Nom d'utilisateur</label>
                <input type="text" id="logUsername" class="input-with-icon" style="width: 100%; padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md); background: var(--bg-secondary); color: var(--text-primary); margin-bottom: 1rem;">
                <label>Mot de passe</label>
                <input type="password" id="logPass" class="input-with-icon" style="width: 100%; padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md); background: var(--bg-secondary); color: var(--text-primary); margin-bottom: 1.5rem;">
                <button class="btn-primary" style="width: 100%" onclick="app.doLogin()">Se connecter</button>
            </div>
            <p style="text-align: center; margin-top: 1rem; font-size: 0.9rem;">Pas de compte ? <a href="#" onclick="app.navigate('register')">S'inscrire</a></p>
        </div>
    `;
}

function renderRegister() {
    return `
        <div style="max-width: 500px; margin: 4rem auto; background: var(--bg-card); padding: 2rem; border-radius: var(--radius-lg); border: 1px solid var(--border-color);">
            <h2 style="margin-bottom: 1.5rem; text-align: center;">Inscription Gadz'arts</h2>
            <div class="trade-input-group">
                <label>Nom Complet *</label>
                <input type="text" id="regName" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:0.75rem;">
                <div style="display:flex; gap: 1rem;">
                    <div style="flex:1"><label>Buque</label><input type="text" id="regBuque" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:0.75rem;"></div>
                    <div style="flex:1"><label>Num's</label><input type="text" id="regNums" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:0.75rem;"></div>
                    <div style="flex:1"><label>Prom's</label><input type="text" id="regProms" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:0.75rem;"></div>
                </div>
                <label>Nom d'utilisateur (Login) *</label>
                <input type="text" id="regUsername" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:0.75rem;">
                <label>Mot de passe (Login) *</label>
                <input type="password" id="regPass" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:1.5rem;">
                <button class="btn-primary" style="width: 100%" onclick="app.doRegister()">S'inscrire (Nécessite Validation)</button>
            </div>
        </div>
    `;
}

function renderProposals() {
    if (!state.currentUser) return `<h1>Accès Refusé.</h1>`;
    
    let html = `
        <div style="margin-bottom: 2rem"><button class="btn-outline" onclick="app.navigate('dashboard')"><i class="fa-solid fa-arrow-left"></i> Retour</button></div>
        <h1 class="page-title"><i class="fa-solid fa-lightbulb"></i> Proposer un Pari</h1>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 2rem;">
            <div class="trade-section" style="height: fit-content;">
                <h2>Soumettre une idée au BDE</h2>
                <div class="trade-input-group">
                    <label>Question du pari</label>
                    <input type="text" id="propTitle" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:1rem;" placeholder="Ex: Qui gagnera l'élection ?">
                    
                    <label>Choix possibles (séparés par des virgules)</label>
                    <input type="text" id="propChoices" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:1rem;" placeholder="Ex: Option A, Option B, Indécis">

                    <label>Image d'illustration (URL optionnelle)</label>
                    <input type="text" id="propImage" style="width:100%; padding:0.75rem; border:1px solid var(--border-color); border-radius:var(--radius-md); background:var(--bg-secondary); color:var(--text-primary); margin-bottom:1rem;" placeholder="https://...">
                    
                    <button class="btn-primary btn-block" onclick="app.submitProposal()">Envoyer ma proposition</button>
                </div>
            </div>
            <div class="trade-section">
                <h2>Mes propositions passées</h2>
                <div class="users-list">
    `;
    
    const myProps = state.data.proposals.filter(p => p.authorId === state.currentUser.id);
    if(myProps.length === 0) {
        html += `<p style="color:var(--text-secondary)">Vous n'avez pas encore proposé de paris.</p>`;
    } else {
        myProps.forEach(p => {
            let statusColor = p.status === 'approved' ? 'var(--yes-color)' : (p.status === 'rejected' ? 'var(--no-color)' : '#ff9800');
            let statusText = p.status === 'approved' ? 'Approuvé' : (p.status === 'rejected' ? 'Rejeté' : 'En attente');
            let note = p.adminNote ? `<div style="font-size:0.8rem; margin-top:0.5rem; padding:0.5rem; background:var(--bg-secondary); border-left:3px solid ${statusColor}">${p.adminNote}</div>` : '';
            html += `
                <div class="user-row" style="flex-direction:column; align-items:flex-start; border-color:${statusColor}">
                    <div style="display:flex; justify-content:space-between; width:100%">
                        <strong>${p.title}</strong>
                        <span class="badge" style="background:${statusColor}">${statusText}</span>
                    </div>
                    <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:0.3rem">Choix: ${p.choices.join(', ')}</div>
                    ${note}
                </div>
            `;
        });
    }
    html += `</div></div></div>`;
    return html;
}

function renderDashboard() {
    const isLeaderboard = state.dashTab === 'leaderboard';


    // ─── ONGLETS ───────────────────────────────────────────────────
    const tabBar = `
        <div style="display:flex; gap:0; margin-bottom:2rem; border-bottom:2px solid var(--border-color);">
            <button
                onclick="app.switchTab('markets')"
                style="padding:0.6rem 1.4rem; font-weight:700; font-size:0.95rem; border:none;
                       background:none; cursor:pointer; transition:all 0.2s;
                       color:${!isLeaderboard ? 'var(--accent-color)' : 'var(--text-secondary)'};
                       border-bottom:${!isLeaderboard ? '3px solid var(--accent-color)' : '3px solid transparent'};
                       margin-bottom:-2px;">
                <i class="fa-solid fa-fire"></i> Paris
            </button>
            <button
                onclick="app.switchTab('leaderboard')"
                style="padding:0.6rem 1.4rem; font-weight:700; font-size:0.95rem; border:none;
                       background:none; cursor:pointer; transition:all 0.2s;
                       color:${isLeaderboard ? 'var(--accent-color)' : 'var(--text-secondary)'};
                       border-bottom:${isLeaderboard ? '3px solid var(--accent-color)' : '3px solid transparent'};
                       margin-bottom:-2px;">
                <i class="fa-solid fa-trophy"></i> Classement
            </button>
        </div>
    `;

    // ─── ONGLET CLASSEMENT ─────────────────────────────────────────
    if (isLeaderboard) {
        let lb = state.leaderboard;
        
        // Fonction pour calculer les points totaux (libres + investis) d'un utilisateur
        const getTotalPoints = (u) => {
            let invested = 0;
            state.data.markets.forEach(m => {
                if (m.status === 'open') {
                    m.bets.forEach(b => {
                        if (b.userId === u.id) invested += b.amount;
                    });
                }
            });
            return Math.max(0, Math.floor(u.points || 0)) + invested;
        };

        if (!state.useApi || !lb || lb.length === 0) {
            lb = Object.values(state.data.users)
                .filter(u => u.status === 'active')
                .sort((a, b) => getTotalPoints(b) - getTotalPoints(a))
                .slice(0, 20)
                .map(u => ({ id: u.id, name: u.name, points: getTotalPoints(u) }));
        }

        // Rang de l'utilisateur courant (peut ne pas être dans le top 20)
        let myRankHtml = '';
        if (state.currentUser) {
            const myRankIdx = lb.findIndex(u => u.id === state.currentUser.id);
            if (myRankIdx === -1) {
                // L'utilisateur n'est pas dans le top 20 : calculer son rang réel
                const allSorted = Object.values(state.data.users)
                    .filter(u => u.status === 'active')
                    .sort((a, b) => getTotalPoints(b) - getTotalPoints(a));
                const realRank = allSorted.findIndex(u => u.id === state.currentUser.id) + 1;
                if (realRank > 0) {
                    const myTotal = state.useApi ? 
                        (state.leaderboard.find(u => u.id === state.currentUser.id)?.points || getTotalPoints(state.currentUser)) : 
                        getTotalPoints(state.currentUser);
                    myRankHtml = `
                        <div style="margin-top:1rem; padding-top:1rem; border-top:2px dashed var(--border-color);">
                            <div class="leaderboard-row me">
                                <span class="leaderboard-rank" style="width:2rem;">#${realRank}</span>
                                <span class="leaderboard-name">${state.currentUser.name} <span style="font-size:0.75rem;opacity:0.7">(moi)</span></span>
                                <span class="leaderboard-pts">${myTotal} pts</span>
                            </div>
                        </div>
                    `;
                }
            }
        }

        const medals = ['🥇','🥈','🥉'];
        const rows = lb.map((u, i) => {
            const isMe = state.currentUser && u.id === state.currentUser.id;
            const rank = i < 3 ? medals[i] : `#${i+1}`;
            const rankClass = i < 3 ? ['top1','top2','top3'][i] : '';
            return `
                <div class="leaderboard-row ${isMe ? 'me' : ''}">
                    <span class="leaderboard-rank ${rankClass}" style="width:2.5rem; font-size:${i<3?'1.1rem':'0.85rem'}">${rank}</span>
                    <span class="leaderboard-name">${u.name}${isMe ? ' <span style="font-size:0.75rem;opacity:0.7">(moi)</span>' : ''}</span>
                    <span class="leaderboard-pts">${u.points} pts</span>
                </div>
            `;
        }).join('');

        // Bonus quotidien
        const today = new Date().toISOString().slice(0, 10);
        const canClaim = state.currentUser && (state.currentUser.lastClaim || '') !== today;
        const claimSection = state.currentUser ? `
            <div style="margin-top:1.5rem; padding-top:1rem; border-top:1px solid var(--border-color);">
                <button class="daily-claim-btn" ${canClaim ? '' : 'disabled'} onclick="app.claimDaily()">
                    <i class="fa-solid fa-gift"></i>
                    ${canClaim ? "R\u00e9cup\u00e9rer mes +5 pts du jour" : "Bonus d\u00e9j\u00e0 r\u00e9cup\u00e9r\u00e9 aujourd\u2019hui \u2714"}
                </button>
            </div>
        ` : '';

        const leaderboardContent = `
            <div style="max-width:640px; margin:0 auto;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem;">
                    <h2 style="font-size:1.3rem; font-weight:700; color:var(--text-primary);">
                        <i class="fa-solid fa-trophy" style="color:#fbbf24;"></i> Top 20
                    </h2>
                    <span style="font-size:0.8rem; color:var(--text-secondary);">Points totaux</span>
                </div>
                <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:var(--radius-lg); overflow:hidden; padding:0.5rem;">
                    ${lb.length === 0
                        ? '<p style="padding:1rem;color:var(--text-secondary);">Aucun joueur pour le moment.</p>'
                        : rows}
                    ${myRankHtml}
                </div>
                ${claimSection}
            </div>
        `;

        return `<div>${tabBar}${leaderboardContent}</div>`;
    }

    // ─── ONGLET PARIS ──────────────────────────────────────────────
    // Restriction : non-connectés ne voient pas les paris
    if (!state.currentUser) {
        return `<div>${tabBar}<div style="max-width:480px; margin:4rem auto; text-align:center; background:var(--bg-card); border:1px solid var(--border-color); border-radius:var(--radius-lg); padding:2.5rem;">
            <i class="fa-solid fa-lock" style="font-size:2.5rem; color:var(--accent-color); margin-bottom:1rem; display:block;"></i>
            <h2 style="margin-bottom:0.75rem;">Accès réservé</h2>
            <p style="color:var(--text-secondary); margin-bottom:1.5rem;">Connectez-vous pour voir les paris en cours et y participer.</p>
            <div style="display:flex; gap:1rem; justify-content:center;">
                <button class="btn-primary" onclick="app.navigate('login')">Se connecter</button>
                <button class="btn-outline" onclick="app.navigate('register')">S'inscrire</button>
            </div>
        </div></div>`;
    }

    const allMarkets = [...state.data.markets].reverse();
    const openMarkets = allMarkets.filter(m => m.status !== 'resolved');
    const closedMarkets = allMarkets.filter(m => m.status === 'resolved');

    const myBetMarketIds = new Set();
    if (state.currentUser) {
        state.data.markets.forEach(m => {
            if (m.bets.some(b => b.userId === state.currentUser.id))
                myBetMarketIds.add(m.id);
        });
    }

    function renderMarketCard(m) {
        const hasMyBet = myBetMarketIds.has(m.id);
        const probs = getProbabilities(m);
        const sortedOpts = [...m.options].sort((a,b) => probs[b.id] - probs[a.id]);
        let probsHtml = '';
        sortedOpts.slice(0, 3).forEach(opt => {
            probsHtml += `
                <div style="display:flex; justify-content:space-between; margin-bottom:0.2rem; font-size:0.85rem; font-weight:600;">
                    <span style="color:${opt.color}">${opt.label}</span>
                    <span style="color:var(--text-primary)">${probs[opt.id]}%</span>
                </div>
            `;
        });
        // Badge "Ma mise" injecté directement dans le HTML
        const myBetBadge = hasMyBet
            ? `<span style="display:inline-block; font-size:0.7rem; font-weight:700;
                           padding:0.15rem 0.45rem; border-radius:20px;
                           background:var(--accent-color); color:white;
                           margin-left:0.5rem; vertical-align:middle;">
                   💰 Ma mise
               </span>`
            : '';
        const cardStyle = hasMyBet
            ? `border:2px solid var(--accent-color); box-shadow:0 0 0 3px var(--accent-transparent);`
            : '';
        return `
            <div class="market-card" style="${cardStyle}" onclick="app.navigate('market', '${m.id}')">
               <div class="market-card-header">
                    <div class="market-icon"><img src="${m.image}" alt=""></div>
                    <div style="display:flex; flex-direction:column; align-items:flex-end;">
                        ${m.status === 'resolved' ? `<span style="font-size:0.7rem; padding:0.2rem 0.5rem; background:var(--bg-secondary); border-radius:4px; font-weight:bold; color:var(--text-secondary); margin-bottom:0.3rem;">CLÔTURÉ</span>` : ''}
                        ${m.status === 'paused' ? `<span style="font-size:0.7rem; padding:0.2rem 0.5rem; background:var(--accent-transparent); border-radius:4px; font-weight:bold; color:var(--accent-color); margin-bottom:0.3rem;">PAUSE</span>` : ''}
                        <span class="market-volume"><i class="fa-solid fa-chart-simple"></i> Vol: ${m.volume} pts</span>
                    </div>
                </div>
                <h3 class="market-title">${m.title}${myBetBadge}</h3>
                <div style="margin-top:0.5rem">${probsHtml}</div>
            </div>
        `;
    }

    const modeIndicator = state.useApi
        ? '<div style="margin-bottom:1rem; font-size:0.8rem; color:var(--yes-color)"><i class="fa-solid fa-server"></i> Connecté au serveur</div>'
        : '<div style="margin-bottom:1rem; font-size:0.8rem; color:#ff9800"><i class="fa-solid fa-database"></i> Mode local</div>';

    let marketsHtml = modeIndicator;
    marketsHtml += `<h2 style="font-size:1.1rem; font-weight:700; margin-bottom:1rem; color:var(--text-primary);"><i class="fa-solid fa-fire" style="color:var(--accent-color);"></i> Paris en cours</h2>`;
    if (openMarkets.length === 0) {
        marketsHtml += `<p style="color:var(--text-secondary); margin-bottom:2rem;">Aucun pari en cours pour le moment.</p>`;
    } else {
        marketsHtml += `<div class="market-grid">`;
        openMarkets.forEach(m => { marketsHtml += renderMarketCard(m); });
        marketsHtml += `</div>`;
    }
    if (closedMarkets.length > 0) {
        marketsHtml += `<h2 style="font-size:1rem; font-weight:700; margin-top:2.5rem; margin-bottom:1rem; color:var(--text-secondary);"><i class="fa-solid fa-flag-checkered"></i> Paris clôturés</h2>`;
        marketsHtml += `<div class="market-grid">`;
        closedMarkets.forEach(m => { marketsHtml += renderMarketCard(m); });
        marketsHtml += `</div>`;
    }

    return `<div>${tabBar}${marketsHtml}</div>`;
}

function renderMarket(id) {
    const m = state.data.markets.find(m => m.id === id);
    if (!m) return `<p>Introuvable</p>`;

    const probs = getProbabilities(m);
    
    let tabsHtml = '';
    m.options.forEach(opt => {
        const isActive = state.selectedOptionId === opt.id;
        // Stats par option
        const optBets = m.bets.filter(b => b.optId === opt.id);
        const optTotal = optBets.reduce((s, b) => s + b.amount, 0);
        const optInvestors = new Set(optBets.map(b => b.userId)).size;
        const statsLabel = optTotal > 0
            ? `<span style="display:block; font-size:0.68rem; opacity:0.85; margin-top:0.15rem;">${optTotal} pts • ${optInvestors} inv.</span>`
            : '';
        tabsHtml += `
            <div class="trade-tab ${isActive ? 'active' : ''}" 
                 style="background: ${isActive ? opt.color : 'transparent'}; 
                        color: ${isActive ? '#fff' : 'var(--text-secondary)'};
                        text-shadow: ${isActive ? '0 1px 2px rgba(0,0,0,0.5)' : 'none'};
                        border: 1px solid ${isActive ? opt.color : 'transparent'};
                        opacity: ${isActive ? '1' : '0.7'}; cursor: pointer;"
                 onclick="app.selectOption('${opt.id}')">
                ${opt.label} ${probs[opt.id]}%
                ${statsLabel}
            </div>
        `;
    });

    const selectedOpt = m.options.find(o => o.id === state.selectedOptionId) || m.options[0];
    const isResolved = m.status === 'resolved';
    const isPaused = m.status === 'paused';
    
    let tradeInterfaceHtml = '';
    
    if (isResolved) {
        tradeInterfaceHtml = m.resolvedWinner === 'cancelled' 
            ? `<div style="padding: 1.5rem; background: var(--bg-secondary); border-radius: var(--radius-md); text-align: center; font-weight: bold; color: var(--text-secondary);">Ce pari a été annulé par le BDE et toutes les mises ont été remboursées à leurs propriétaires.</div>`
            : `<div style="padding: 1.5rem; background: ${m.options.find(o=>o.id === m.resolvedWinner)?.color || 'var(--yes-color)'}; border-radius: var(--radius-md); text-align: center; font-weight: bold; color: white; text-shadow: 0 1px 2px rgba(0,0,0,0.5);">Pari clôturé !<br><br>Gagnant : ${m.options.find(o=>o.id === m.resolvedWinner)?.label}</div>`;
    } else if (isPaused) {
        tradeInterfaceHtml = `<div style="padding: 1.5rem; background: var(--accent-transparent); border-radius: var(--radius-md); text-align: center; font-weight: bold; color: var(--accent-color); border: 1px solid var(--accent-color);">Le BDE a suspendu ce pari temporairement. Les transactions et retraits sont gelés.</div>`;
    } else {
        tradeInterfaceHtml = `
                <div class="trade-input-group">
                    <label>Montant (pts)</label>
                    <div class="input-with-icon">
                        <i class="fa-solid fa-coins"></i>
                        <input type="number" id="betAmount" placeholder="0" min="1" value="10" oninput="app.updateGainEstimate()">
                    </div>
                </div>

                <div class="return-estimate">
                    <span>Retour potentiel:</span>
                    <span id="gainEstimateValue" style="color: ${selectedOpt.color}; font-weight: 700;">
                        ~ Calcul en cours...
                    </span>
                </div>

                <button id="betBtn" class="btn-block" style="background: ${selectedOpt.color || 'var(--accent-color)'}; color: white; border-radius: var(--radius-md); font-weight: 600; box-shadow: 0 4px 10px rgba(0,0,0,0.15); text-shadow: 0 1px 2px rgba(0,0,0,0.3);" onclick="app.placeBet()">
                    Miser sur ${selectedOpt.label}
                </button>
                
                ${!state.currentUser ? '<p style="text-align:center; color: var(--no-color); font-size:0.9rem; margin-top:1rem">Connectez-vous pour miser.</p>' : ''}
        `;
    }
    
    let portfolioHtml = '';
    if (state.currentUser) {
        const myBets = m.bets.filter(b => b.userId === state.currentUser.id);
        if(myBets.length > 0) {
            portfolioHtml = `<div style="margin-top: 2rem; border-top: 1px solid var(--border-color); padding-top: 1.5rem;">
                <h3 style="margin-bottom: 1rem; color: var(--text-primary);"><i class="fa-solid fa-briefcase"></i> Mes Positions</h3>
                <div style="display: flex; flex-direction: column; gap: 0.75rem;">`;
            myBets.forEach(b => {
                const opt = m.options.find(o => o.id === b.optId);
                const proxyBet = { amount: b.amount, optId: b.optId };
                const currentProb = getAdjustedProbabilities(m, proxyBet)[b.optId] || 1;
                const rawValue = b.amount * (currentProb / (b.buyProb || 1));
                const cashoutVal = Math.floor(rawValue * 0.97);
                const pnl = cashoutVal - b.amount;
                const pnlColor = pnl > 0 ? 'var(--yes-color)' : (pnl < 0 ? 'var(--no-color)' : 'var(--text-secondary)');
                const inputId = `sellAmt_${b.id}`;

                let sellSection = '';
                if (m.status === 'open') {
                    sellSection = `
                        <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; margin-top:0.5rem;">
                            <input type="number" id="${inputId}" min="1" max="${b.amount}" value="${b.amount}"
                                style="width:80px; padding:0.3rem 0.5rem; border-radius:var(--radius-sm); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary); font-size:0.85rem;"
                                placeholder="Qté">
                            <span style="font-size:0.8rem; color:var(--text-secondary);">/ ${b.amount} pts</span>
                            <button class="btn-outline" style="font-size:0.8rem; padding:0.3rem 0.6rem; border-color:${pnl>0?'var(--yes-color)':'var(--border-color)'}"
                                onclick="app.cashOutBet('${m.id}', '${b.id}', parseInt(document.getElementById('${inputId}').value) || ${b.amount})">
                                <i class="fa-solid fa-money-bill-transfer"></i> Revendre
                            </button>
                        </div>`;
                }

                portfolioHtml += `
                    <div style="background: var(--bg-card); padding: 0.75rem; border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <span style="font-weight:bold; color:${opt.color}; text-shadow:0 1px 2px rgba(0,0,0,0.1)">${opt.label}</span>
                                <span style="font-size:0.8rem; color:var(--text-secondary); margin-left:0.5rem">Mise: ${b.amount} pts</span>
                                <span style="font-size:0.8rem; margin-left:0.5rem; color:${pnlColor}; font-weight:bold">P&L: ${pnl > 0 ? '+' : ''}${pnl} pts</span>
                            </div>
                            <span style="font-size:0.78rem; color:var(--text-secondary);">Valeur: ~${cashoutVal} pts</span>
                        </div>
                        ${sellSection}
                    </div>
                `;
            });
            portfolioHtml += `</div></div>`;
        }
    }

    return `
        <button class="btn-outline" style="margin-bottom: 2rem" onclick="app.navigate('dashboard')">
            <i class="fa-solid fa-arrow-left"></i> Retour
        </button>
        
        <div class="detail-layout">
            <div class="chart-section">
                <div class="chart-header" style="display:flex; justify-content:space-between; align-items:flex-start; gap:1rem;">
                    <div style="display:flex; align-items:center; gap:1rem;">
                        <img src="${m.image}" alt="" style="width: 56px; height: 56px; border-radius: 8px; flex-shrink:0;">
                        <h1 style="font-size: 1.3rem; line-height:1.3;">${m.title}</h1>
                    </div>
                    <button class="chart-toggle-btn" onclick="app.toggleChart()" id="chartToggleBtn">
                        ${state.chartHidden ? '<i class="fa-solid fa-chart-line"></i> Afficher' : '<i class="fa-solid fa-eye-slash"></i> Masquer'} le graphe
                    </button>
                </div>
                <div id="chartWrapper" style="flex:1; width:100%; min-height: 300px; position:relative; ${state.chartHidden ? 'display:none' : ''}">
                    <canvas id="marketChart"></canvas>
                </div>
            </div>

            <div class="trade-section">
                <div style="display: flex; justify-content: space-between; align-items: baseline">
                    <h2>Miser</h2>
                </div>
                
                <div class="trade-tabs" style="flex-wrap: wrap; gap: 0.25rem;">
                    ${tabsHtml}
                </div>

                ${tradeInterfaceHtml}
                ${portfolioHtml}
            </div>
        </div>
    `;
}

function renderAdmin() {
    if (!state.currentUser || state.currentUser.role !== 'admin') return `<h1>Accès Refusé.</h1>`;

    let activeUsers = '';
    let pendingUsers = '';
    Object.values(state.data.users).forEach(u => {
        let details = `Buque: ${u.buque || '-'}, Num's: ${u.nums || '-'}, Prom's: ${u.proms || '-'}`;
        if (u.status === 'pending') {
            pendingUsers += `
                <div class="user-row" style="border-color: #ff9800;">
                    <div>
                        <span style="font-weight: 600">${u.name} (@${u.username})</span> <br>
                        <span style="font-size: 0.8rem; color: var(--text-secondary)">${details}</span>
                    </div>
                    <div>
                        <button class="btn-primary" onclick="app.approveUser('${u.id}')">Accepter</button>
                        <button class="btn-outline" onclick="app.rejectUser('${u.id}')">Rejeter</button>
                    </div>
                </div>
            `;
        } else {
            activeUsers += `
                <div class="user-row">
                    <div>
                        <span style="font-weight: 600">${u.name}</span>
                        <span style="color: var(--text-secondary); margin-left:1rem"><i class="fa-solid fa-coins"></i> ${Math.floor(u.points)} pts</span>
                        <br><span style="font-size: 0.8rem; color: var(--text-secondary)">${details}</span>
                    </div>
                    <div style="display:flex; gap:0.5rem; flex-wrap:wrap; justify-content:flex-end;">
                        <button class="btn-outline" onclick="app.grantPoints('${u.id}')"><i class="fa-solid fa-coins"></i> Points</button>
                        <button class="btn-outline" onclick="app.viewUserHistory('${u.id}', '${u.name}')"><i class="fa-solid fa-clock-rotate-left"></i></button>
                        ${state.currentUser.id === 'admin' && u.id !== 'admin' ? 
                            `<button class="btn-outline" onclick="app.toggleAdmin('${u.id}')"><i class="fa-solid fa-star"></i> ${u.role === 'admin' ? 'Retirer Admin' : 'Nommer Admin'}</button>` 
                            : ''}
                        ${state.currentUser.id === 'admin' && u.id !== 'admin' ?
                            `<button class="btn-outline" style="color:#ef4444;border-color:#ef4444" onclick="app.deleteUser('${u.id}', '${u.name}')"><i class="fa-solid fa-user-slash"></i></button>`
                            : ''}
                    </div>
                </div>
            `;
        }
    });

    let adminMarketsHtml = '';
    state.data.markets.forEach(m => {
        let statusBadge = '';
        if(m.status === 'resolved') statusBadge = `<span style="font-weight:bold; font-size: 0.8rem; padding:0.2rem 0.5rem; background:var(--bg-secondary); border-radius:4px; color:var(--text-secondary); margin-left:1rem;">CLÔTURÉ</span>`;
        else if(m.status === 'paused') statusBadge = `<span style="font-weight:bold; font-size: 0.8rem; padding:0.2rem 0.5rem; background:var(--accent-transparent); border-radius:4px; color:var(--accent-color); border: 1px solid var(--accent-color); margin-left:1rem;">EN PAUSE</span>`;
        
        let btns = '';
        if (m.status === 'open') {
            btns = `<button class="btn-outline" style="margin-right: 0.5rem" onclick="app.togglePause('${m.id}')">Bloquer</button>
                    <button class="btn-primary" onclick="app.resolveMarketPrompt('${m.id}')">Clôturer</button>`;
        } else if (m.status === 'paused') {
            btns = `<button class="btn-outline" style="margin-right: 0.5rem" onclick="app.togglePause('${m.id}')">Débloquer</button>
                    <button class="btn-primary" onclick="app.resolveMarketPrompt('${m.id}')">Clôturer</button>`;
        } else if (m.status === 'resolved') {
            btns = `<button class="btn-outline" style="color:var(--error-color); border-color:var(--error-color);" onclick="app.deleteMarket('${m.id}')"><i class="fa-solid fa-trash"></i> Supprimer</button>`;
        }

        adminMarketsHtml += `
            <div class="user-row">
                <div style="flex:1;"><span style="font-weight: 600">${m.title}</span> ${statusBadge}</div>
                <div>${btns}</div>
            </div>
        `;
    });

    let pendingProposalsHtml = '';
    const pendingProps = state.data.proposals.filter(p => p.status === 'pending');
    pendingProps.forEach(p => {
        pendingProposalsHtml += `
            <div class="user-row" style="border-color: #3b82f6; flex-direction:column; align-items:stretch; gap: 0.5rem;">
                <div>
                    <span style="font-weight: 600">${p.title}</span> <span style="font-size:0.8rem; color:var(--text-secondary)">- par ${p.authorName}</span>
                </div>
                <div style="font-size: 0.85rem;">Choix: ${p.choices.join(', ')}</div>
                <div style="display:flex; justify-content:flex-end; gap:0.5rem; margin-top:0.5rem;">
                    <button class="btn-outline" onclick="app.rejectProposal('${p.id}')">Rejeter</button>
                    <button class="btn-primary" onclick="app.approveProposal('${p.id}')">Approuver & Créer Marché</button>
                </div>
            </div>
        `;
    });

    return `
        <div style="margin-bottom: 2rem"><button class="btn-outline" onclick="app.navigate('dashboard')"><i class="fa-solid fa-arrow-left"></i> Retour</button></div>
        <h1 class="page-title"><i class="fa-solid fa-shield-halved"></i> Panel d'Administration</h1>
        
        <div class="admin-card" style="background: rgba(59, 130, 246, 0.1); border-color: #3b82f6;">
            <h2 class="admin-header" style="color: #3b82f6;"><i class="fa-solid fa-lightbulb"></i> Propositions de paris</h2>
            ${pendingProps.length === 0 ? '<p>Aucune proposition en attente.</p>' : `<div class="users-list">${pendingProposalsHtml}</div>`}
        </div>

        <div class="admin-card" style="background: rgba(255, 152, 0, 0.1); border-color: #ff9800;">
            <h2 class="admin-header" style="color: #ff9800;"><i class="fa-solid fa-user-clock"></i> Inscriptions en attente</h2>
            ${pendingUsers === '' ? '<p>Aucune inscription en attente.</p>' : `<div class="users-list">${pendingUsers}</div>`}
        </div>

        ${(() => {
            const ncReqs = state.data.nameChangeRequests || [];
            if (ncReqs.length === 0) return '';
            const ncHtml = ncReqs.map(r => `
                <div class="user-row" style="border-color:#a855f7; flex-direction:column; align-items:stretch; gap:0.4rem;">
                    <div><strong>${r.oldName}</strong> <i class="fa-solid fa-arrow-right" style="color:var(--text-secondary)"></i> <strong style="color:#a855f7">${r.newName}</strong></div>
                    <div style="display:flex; justify-content:flex-end; gap:0.5rem;">
                        <button class="btn-outline" onclick="app.rejectNameChange('${r.id}')">Rejeter</button>
                        <button class="btn-primary" style="background:#a855f7" onclick="app.approveNameChange('${r.id}')">Approuver</button>
                    </div>
                </div>`).join('');
            return `<div class="admin-card" style="background:rgba(168,85,247,0.08); border-color:#a855f7;">
                <h2 class="admin-header" style="color:#a855f7;"><i class="fa-solid fa-pen"></i> Demandes de pseudonyme</h2>
                <div class="users-list">${ncHtml}</div>
            </div>`;
        })()}

        <div class="admin-card">
            <h2 class="admin-header"><i class="fa-solid fa-chart-pie"></i> Marchés Actifs</h2>
            <button class="btn-primary" style="margin-bottom:1rem" onclick="app.createMarketDirect()">+ Créer un Marché Officiel</button>
            <div class="users-list">${adminMarketsHtml}</div>
        </div>

        <div class="admin-card">
            <h2 class="admin-header"><i class="fa-solid fa-users"></i> Membres Actifs &amp; Points</h2>
            <div class="users-list">${activeUsers}</div>
        </div>

        ${state.currentUser.id === 'admin' ? `
        <div class="admin-card" style="background:rgba(239,68,68,0.07); border-color:#ef4444;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h2 class="admin-header" style="color:#ef4444; margin:0;"><i class="fa-solid fa-receipt"></i> Journal des crédits admin</h2>
                <button class="btn-outline" style="border-color:#ef4444; color:#ef4444" onclick="app.viewGrantsLog()"><i class="fa-solid fa-eye"></i> Voir le journal</button>
            </div>
        </div>` : ''}
    `;
}

// --- CHARTS ---
let currentChart = null;

function initChart(marketId) {
    const canvas = document.getElementById('marketChart');
    if (!canvas) return;
    if (currentChart) currentChart.destroy();

    const ctx = canvas.getContext('2d');
    const market = state.data.markets.find(m => m.id === marketId);
    const isDark = state.theme === 'dark';

    // Formater les labels : ISO -> timestamp (pour axe X linéaire)
    let lastValidTime = Date.now() - 3600000;
    const historyData = market.history.map((h, i) => {
        let xVal = lastValidTime + (i * 1000); // fallback léger espacement
        if (h.time && (h.time.includes('T') || h.time.includes('-'))) {
            const ms = new Date(h.time).getTime();
            if (!isNaN(ms)) {
                xVal = ms;
                lastValidTime = ms;
            }
        }
        return { ...h, xVal };
    });

    const datasets = market.options.map(opt => ({
        label: opt.label,
        data: historyData.map(h => ({ x: h.xVal, y: h[opt.id] })),
        borderColor: opt.color,
        backgroundColor: 'transparent',
        borderWidth: 4,
        tension: 0.4,
        pointRadius: 5,
        pointHoverRadius: 8
    }));

    currentChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: isDark ? '#a0a0a0' : '#666666' } },
                tooltip: {
                    mode: 'index', intersect: false,
                    callbacks: {
                        title: (tooltipItems) => {
                            if (!tooltipItems.length) return '';
                            const d = new Date(tooltipItems[0].parsed.x);
                            return d.toLocaleDateString('fr-FR', { day:'2-digit', month:'2-digit' }) + ' ' + d.toLocaleTimeString('fr-FR', { hour:'2-digit', minute:'2-digit' });
                        },
                        label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}%`
                    }
                }
            },
            scales: {
                y: {
                    min: 0, max: 100,
                    grid: { color: isDark ? '#333333' : '#e5e5e5' },
                    ticks: { color: isDark ? '#a0a0a0' : '#666666', callback: v => v + '%' }
                },
                x: {
                    type: 'linear',
                    grid: { display: false },
                    ticks: {
                        color: isDark ? '#a0a0a0' : '#666666',
                        maxRotation: 30, maxTicksLimit: 10,
                        callback: function(value) {
                            const d = new Date(value);
                            return d.toLocaleTimeString('fr-FR', { hour:'2-digit', minute:'2-digit' });
                        }
                    }
                }
            },
            interaction: { mode: 'nearest', axis: 'x', intersect: false }
        }
    });

    app.updateGainEstimate();
}

// ─────────────────────────────────────────────────────────────────────────────
// PAGE PROFIL
// ─────────────────────────────────────────────────────────────────────────────
function renderProfile() {
    if (!state.currentUser) return renderLogin();
    const u = state.currentUser;
    const txs = (state.useApi ? [] : (u.transactions || []));

    // Si on est en mode API, on charge les transactions asynchronement
    if (state.useApi) {
        fetch(`/api/users/${u.id}/transactions`)
            .then(r => r.json())
            .then(data => {
                const list = document.getElementById('txList');
                if (!list) return;
                list.innerHTML = data.length === 0
                    ? '<p style="color:var(--text-secondary);text-align:center;">Aucune transaction pour le moment.</p>'
                    : data.map(tx => formatTxRow(tx)).join('');
            }).catch(() => {});
    }

    const txHtml = state.useApi
        ? '<p style="color:var(--text-secondary);text-align:center;"><i class="fa-solid fa-spinner fa-spin"></i> Chargement...</p>'
        : (txs.length === 0
            ? '<p style="color:var(--text-secondary);text-align:center;">Aucune transaction pour le moment.</p>'
            : txs.map(tx => formatTxRow(tx)).join(''));

    return `
        <div style="margin-bottom: 2rem">
            <button class="btn-outline" onclick="app.navigate('dashboard')">
                <i class="fa-solid fa-arrow-left"></i> Retour
            </button>
        </div>

        <h1 class="page-title"><i class="fa-solid fa-circle-user"></i> Mon Profil</h1>

        <div class="admin-card">
            <h2 class="admin-header"><i class="fa-solid fa-id-card"></i> Informations</h2>
            <div class="user-row" style="flex-direction:column; align-items:flex-start; gap:0.4rem;">
                <div><strong>Nom :</strong> ${u.name}</div>
                <div><strong>Identifiant :</strong> ${u.username}</div>
                <div><strong>Bu\u00e8que :</strong> ${u.buque || '—'}</div>
                <div><strong>Promotion :</strong> ${u.proms || '—'}</div>
                <div><strong>Num\u00e9ro :</strong> ${u.nums || '—'}</div>
                <div><strong>R\u00f4le :</strong> <span style="color: ${u.role === 'admin' ? 'var(--accent-color)' : 'var(--text-secondary)'}">${u.role === 'admin' ? '⭐ Administrateur' : 'Membre'}</span></div>
                <div style="margin-top:0.5rem; font-size:1.3rem; font-weight:700; color:var(--accent-color)">
                    <i class="fa-solid fa-coins"></i> ${Math.floor(u.points)} points
                </div>
            </div>
        </div>

        <div class="admin-card" style="border-color:#a855f7; background:rgba(168,85,247,0.06);">
            <h2 class="admin-header" style="color:#a855f7;"><i class="fa-solid fa-pen"></i> Changer mon nom affich\u00e9</h2>
            <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:1rem;">
                Nom actuel : <strong>${u.name}</strong>. La demande doit \u00eatre valid\u00e9e par un admin.
            </p>
            <button class="btn-outline" style="border-color:#a855f7; color:#a855f7;" onclick="app.requestNameChange()">
                <i class="fa-solid fa-pen-to-square"></i> Demander un changement de nom
            </button>
        </div>

        <div class="admin-card">
            <h2 class="admin-header"><i class="fa-solid fa-key"></i> Changer mon mot de passe</h2>
            <div style="display:flex; flex-direction:column; gap:0.75rem; max-width:420px;">
                <input id="oldPass" type="password" placeholder="Ancien mot de passe"
                    style="padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);">
                <input id="newPass" type="password" placeholder="Nouveau mot de passe"
                    style="padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);">
                <input id="newPass2" type="password" placeholder="Confirmer le nouveau mot de passe"
                    style="padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);">
                <button class="btn-primary" onclick="app.changePassword()">
                    <i class="fa-solid fa-floppy-disk"></i> Enregistrer
                </button>
            </div>
        </div>

        <div class="admin-card">
            <h2 class="admin-header"><i class="fa-solid fa-clock-rotate-left"></i> Historique des transactions</h2>
            <div id="txList">${txHtml}</div>
        </div>
    `;
}

function formatTxRow(tx) {
    const d = new Date(tx.time);
    const dateStr = d.toLocaleDateString('fr-FR') + ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    let amountHtml = '';
    if (tx.amount > 0) {
        amountHtml = `<span style="color:#22c55e; font-weight:700;">+${tx.amount} pts</span>`;
    } else if (tx.amount < 0) {
        amountHtml = `<span style="color:#ef4444; font-weight:700;">${tx.amount} pts</span>`;
    } else {
        amountHtml = `<span style="color:var(--text-secondary); font-weight:700;">— pts</span>`;
    }
    return `
        <div class="user-row" style="flex-direction:row; justify-content:space-between; align-items:center; gap:1rem;">
            <div>
                <div style="font-weight:600; font-size:0.95rem;">${tx.desc}</div>
                <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:0.1rem;">${dateStr}</div>
            </div>
            <div>${amountHtml}</div>
        </div>
    `;
}

window.addEventListener('DOMContentLoaded', init);
