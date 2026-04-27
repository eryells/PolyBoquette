import os
import re

app_js_path = "js/app.js"

with open(app_js_path, "r", encoding="utf-8") as f:
    content = f.read()

# We will just write a new app.js from scratch using Python to avoid AI token limits
# The new app.js will have the API logic + Proposals.

new_app_js = """
const state = {
    version: 5,
    useApi: false, // Detecté auto au lancement
    currentUser: null,
    theme: 'dark',
    data: {
        users: {
            admin: { id: 'admin', username: 'admin', password: '123', name: 'ADMIN', role: 'admin', status: 'active', points: 1000, buque: 'Admin', nums: '1', proms: 'Me221' },
            user1: { id: 'user1', username: 'jean', password: '123', name: 'Jean Dupont', role: 'user', status: 'active', points: 1000, buque: 'Bab', nums: '123', proms: 'An211' },
        },
        markets: [
            {
                id: 'm1',
                title: 'Notre école sera-t-elle dans le top 10 L\\'Étudiant l\\'an prochain ?',
                image: 'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?auto=format&fit=crop&w=150&q=80',
                volume: 4500,
                status: 'open',
                resolvedWinner: null,
                bets: [],
                options: [
                    { id: 'o1', label: 'Oui', shares: 1500, color: '#0f8b65' },
                    { id: 'o2', label: 'Non', shares: 700, color: '#d13e38' }
                ],
                history: [
                    { time: 'J-6', o1: 40, o2: 60 }, { time: 'J-5', o1: 45, o2: 55 }, { time: 'J-4', o1: 55, o2: 45 },
                    { time: 'J-3', o1: 52, o2: 48 }, { time: 'J-2', o1: 60, o2: 40 }, { time: 'J-1', o1: 68, o2: 32 }
                ]
            }
        ],
        proposals: [] // <-- NOUVEAU
    },
    currentView: 'dashboard',
    currentMarketId: null,
    selectedOptionId: null
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

async function refreshServerData() {
    if(!state.useApi) return;
    const [mRes, pRes] = await Promise.all([
        fetch('/api/markets').catch(()=>null),
        state.currentUser ? fetch('/api/proposals').catch(()=>null) : Promise.resolve(null)
    ]);
    if(mRes && mRes.ok) state.data.markets = await mRes.json();
    if(pRes && pRes.ok) state.data.proposals = await pRes.json();
    
    if(state.currentUser?.role === 'admin') {
        const uRes = await fetch('/api/admin/users').catch(()=>null);
        if(uRes && uRes.ok) {
            const users = await uRes.json();
            state.data.users = {};
            users.forEach(u => state.data.users[u.id] = u);
        }
    } else if (state.currentUser) {
        state.data.users = {};
        state.data.users[state.currentUser.id] = state.currentUser;
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
                await apiCall('POST', `/api/markets/${market.id}/bet`, { optId, amount });
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
            market.bets.push({
                id: 'b' + Date.now() + Math.floor(Math.random()*100),
                userId: state.currentUser.id,
                optId: optId,
                amount: amount,
                buyProb: probs[optId],
                time: new Date().toISOString()
            });
            const now = new Date();
            const timeStr = now.getHours() + ':' + String(now.getMinutes()).padStart(2, '0');
            const historyEntry = { time: timeStr };
            Object.keys(probs).forEach(k => { historyEntry[k] = probs[k] });
            market.history.push(historyEntry);
            saveDataLocal();
            ui.showToast("Mise effectuée avec succès !");
        }
        
        updateNavbar();
        app.navigate('market', market.id); 
    },
    
    cashOutBet: async (marketId, betId) => {
        const market = state.data.markets.find(m => m.id === marketId);
        if (market.status !== 'open') return ui.showToast("Le marché ne permet plus de revente !", 'error');
        
        if (state.useApi) {
            try {
                const res = await apiCall('POST', `/api/markets/${marketId}/cashout/${betId}`);
                ui.showToast(`Vous avez retiré votre liquidité (${res.refund} points).`);
            } catch(e) {
                return ui.showToast(e.message, 'error');
            }
        } else {
            const betIndex = market.bets.findIndex(b => b.id === betId);
            const bet = market.bets[betIndex];
            if(bet.userId !== state.currentUser?.id) return;
            
            const adjustedProbs = getAdjustedProbabilities(market, bet);
            const currentProb = adjustedProbs[bet.optId] || 1;
            const rawValue = bet.amount * (currentProb / (bet.buyProb || 1));
            let refund = Math.floor(rawValue * 0.97);
            if(refund < 0) refund = 1;

            state.currentUser.points += refund;
            market.volume = Math.max(1, market.volume - refund);
            const opt = market.options.find(o => o.id === bet.optId);
            opt.shares = Math.max(1, opt.shares - refund);

            const newProbs = getProbabilities(market);
            const now = new Date();
            const timeStr = now.getHours() + ':' + String(now.getMinutes()).padStart(2, '0');
            const historyEntry = { time: timeStr };
            Object.keys(newProbs).forEach(k => { historyEntry[k] = newProbs[k] });
            market.history.push(historyEntry);
            market.bets.splice(betIndex, 1);
            
            saveDataLocal();
            ui.showToast(`Vous avez retiré votre liquidité (${refund} points).`);
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
            "<i class='fa-solid fa-coins'></i> Assigner des points",
            `
            <label style="display:block; margin-bottom:0.5rem; font-weight:500;">Montant de points :</label>
            <input type="number" id="modalGrantPoints" style="width:100%; padding:0.75rem; border-radius:var(--radius-md); border:1px solid var(--border-color); background:var(--bg-secondary); color:var(--text-primary);" placeholder="ex: 1000">
            `,
            async () => {
                const amount = parseInt(document.getElementById('modalGrantPoints').value);
                if (isNaN(amount) || amount <= 0) return ui.showToast("Montant invalide", "error");
                
                if(state.useApi) {
                    await apiCall('POST', `/api/admin/users/${userId}/grant`, {amount});
                } else {
                    state.data.users[userId].points += amount;
                    saveDataLocal();
                }
                ui.closeModal(true);
                app.navigate('admin');
                ui.showToast(amount + " points accordés.");
            },
            "Accorder"
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
                id: 'o' + (i+1), label: c, shares: 100, color: PALETTE[i % PALETTE.length]
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
                    if (state.data.users[b.userId]) state.data.users[b.userId].points += b.amount;
                });
            } else {
                const winningOpt = market.options.find(o => o.id === winnerId);
                const totalPool = market.volume;
                const winningPool = winningOpt.shares;
                market.bets.forEach(b => {
                    if (b.optId === winnerId && state.data.users[b.userId]) {
                        const sharePercent = b.amount / winningPool;
                        state.data.users[b.userId].points += Math.floor(sharePercent * totalPool);
                    }
                });
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
    let html = `
        <div style="display: flex; justify-content: space-between; align-items: center">
            <h1 class="page-title">Marchés Tendances</h1>
        </div>
        ${state.useApi ? '<div style="margin-bottom:1rem; font-size:0.8rem; color:var(--yes-color)"><i class="fa-solid fa-server"></i> Connecté au serveur en direct</div>' : '<div style="margin-bottom:1rem; font-size:0.8rem; color:#ff9800"><i class="fa-solid fa-database"></i> Mode Local hors-ligne</div>'}
        <div class="market-grid">
    `;

    state.data.markets.forEach(m => {
        const probs = getProbabilities(m);
        const sortedOpts = [...m.options].sort((a,b) => probs[b.id] - probs[a.id]);
        
        let probsHtml = '';
        sortedOpts.slice(0, 3).forEach(opt => {
            probsHtml += `
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.2rem; font-size: 0.85rem; font-weight: 600;">
                    <span style="color: ${opt.color}">${opt.label}</span>
                    <span style="color: var(--text-primary)">${probs[opt.id]}%</span>
                </div>
            `;
        });

        html += `
            <div class="market-card" onclick="app.navigate('market', '${m.id}')">
               <div class="market-card-header">
                    <div class="market-icon"><img src="${m.image}" alt=""></div>
                    <div style="display:flex; flex-direction:column; align-items:flex-end;">
                        ${m.status === 'resolved' ? \`<span style="font-size:0.7rem; padding:0.2rem 0.5rem; background:var(--bg-secondary); border-radius:4px; font-weight:bold; color:var(--text-secondary); margin-bottom:0.3rem;">CLÔTURÉ</span>\` : ''}
                        ${m.status === 'paused' ? \`<span style="font-size:0.7rem; padding:0.2rem 0.5rem; background:var(--accent-transparent); border-radius:4px; font-weight:bold; color:var(--accent-color); margin-bottom:0.3rem;">PAUSE</span>\` : ''}
                        <span class="market-volume"><i class="fa-solid fa-chart-simple"></i> Vol: ${m.volume} pts</span>
                    </div>
                </div>
                <h3 class="market-title">${m.title}</h3>
                <div style="margin-top: 0.5rem">
                    ${probsHtml}
                </div>
            </div>
        `;
    });

    html += `</div>`;
    return html;
}

function renderMarket(id) {
    const m = state.data.markets.find(m => m.id === id);
    if (!m) return `<p>Introuvable</p>`;

    const probs = getProbabilities(m);
    
    let tabsHtml = '';
    m.options.forEach(opt => {
        const isActive = state.selectedOptionId === opt.id;
        tabsHtml += `
            <div class="trade-tab ${isActive ? 'active' : ''}" 
                 style="background: ${isActive ? opt.color : 'transparent'}; 
                        color: ${isActive ? '#fff' : 'var(--text-secondary)'};
                        text-shadow: ${isActive ? '0 1px 2px rgba(0,0,0,0.5)' : 'none'};
                        border: 1px solid ${isActive ? opt.color : 'transparent'};
                        opacity: ${isActive ? '1' : '0.7'}; cursor: pointer;"
                 onclick="app.selectOption('${opt.id}')">
                ${opt.label} ${probs[opt.id]}%
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
                const currentProb = getAdjustedProbabilities(m, b)[b.optId] || 1;
                const rawValue = b.amount * (currentProb / (b.buyProb || 1));
                const cashoutVal = Math.floor(rawValue * 0.97);
                const pnl = cashoutVal - b.amount;
                const pnlColor = pnl > 0 ? 'var(--yes-color)' : (pnl < 0 ? 'var(--no-color)' : 'var(--text-secondary)');

                let sellBtn = m.status === 'open' ? `<button class="btn-outline" style="font-size:0.8rem; padding: 0.25rem 0.5rem; border-color:${pnl>0?'var(--yes-color)':'var(--border-color)'}" onclick="app.cashOutBet('${m.id}', '${b.id}')">Revendre pour ${cashoutVal}pts</button>` : '';

                portfolioHtml += `
                    <div style="display: flex; justify-content: space-between; align-items: center; background: var(--bg-card); padding: 0.75rem; border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                        <div>
                            <span style="font-weight:bold; color:${opt.color}; text-shadow:0 1px 2px rgba(0,0,0,0.1)">${opt.label}</span>
                            <span style="font-size:0.8rem; color:var(--text-secondary); margin-left:0.5rem">Mise: ${b.amount} pts</span>
                            <span style="font-size:0.8rem; margin-left:0.5rem; color:${pnlColor}; font-weight:bold">Profit estimé : ${pnl > 0 ? '+' : ''}${pnl} pts</span>
                        </div>
                        ${sellBtn}
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
                <div class="chart-header">
                    <img src="${m.image}" alt="" style="width: 64px; height: 64px; border-radius: 8px;">
                    <h1 style="font-size: 1.5rem">${m.title}</h1>
                </div>
                <div style="flex:1; width:100%; min-height: 300px; position:relative">
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
                    <button class="btn-outline" onclick="app.grantPoints('${u.id}')"><i class="fa-solid fa-plus"></i> Points</button>
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

        <div class="admin-card">
            <h2 class="admin-header"><i class="fa-solid fa-chart-pie"></i> Marchés Actifs</h2>
            <div class="users-list">${adminMarketsHtml}</div>
        </div>

        <div class="admin-card">
            <h2 class="admin-header"><i class="fa-solid fa-users"></i> Membres Actifs & Points</h2>
            <div class="users-list">${activeUsers}</div>
        </div>
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
    
    const datasets = market.options.map(opt => ({
        label: opt.label,
        data: market.history.map(h => h[opt.id]),
        borderColor: opt.color,
        backgroundColor: 'transparent',
        borderWidth: 4,
        tension: 0.4,
        pointRadius: 5,
        pointHoverRadius: 8
    }));

    currentChart = new Chart(ctx, {
        type: 'line',
        data: { labels: market.history.map(h => h.time), datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: isDark ? '#a0a0a0' : '#666666' } },
                tooltip: {
                    mode: 'index', intersect: false,
                    callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}%` }
                }
            },
            scales: {
                y: {
                    min: 0, max: 100,
                    grid: { color: isDark ? '#333333' : '#e5e5e5' },
                    ticks: { color: isDark ? '#a0a0a0' : '#666666', callback: v => v + '%' }
                },
                x: { grid: { display: false }, ticks: { color: isDark ? '#a0a0a0' : '#666666' } }
            },
            interaction: { mode: 'nearest', axis: 'x', intersect: false }
        }
    });

    app.updateGainEstimate();
}

window.addEventListener('DOMContentLoaded', init);
"""

with open("js/app_new.js", "w", encoding="utf-8") as f:
    f.write(new_app_js)

# Replace old app.js
os.replace("js/app_new.js", app_js_path)
print("app.js rewritten successfully.")
