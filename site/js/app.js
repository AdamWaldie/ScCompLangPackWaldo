/**
 * Pack Merger — main application controller.
 * Wires the UI to the INI parser, category DB and merge engine.
 */

import { parseIni, serializeIni, readFileAsText, downloadIni } from './ini-parser.js';
import { CategoryDB } from './categories.js';
import { MergeEngine } from './merge-engine.js';
import { STOCK_SOURCE, STOCK_VERSION_URL, LANGUAGE_PACK_SOURCES } from './sources.js';

const STATE_KEY = 'pm-state';
// Ship text the component packs own in presets; everything else can come from a second pack.
const COMPONENT_GROUPS = new Set(['Ship Components', 'Ordnance']);
const PRESETS = {
    'remix': ['waldo-remix'],
    'remix-starstrings': ['waldo-remix', 'mrkraken-starstrings'],
    'classic-starstrings': ['waldo-classic', 'mrkraken-starstrings'],
    'reset': [],
};

// Browser storage can be unavailable (private mode, blocked site data); the app works without it.
function loadState() {
    try { return JSON.parse(localStorage.getItem(STATE_KEY)) || null; } catch { return null; }
}
function storeState(state) {
    try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch { /* not persisted */ }
}

class PackMergerApp {
    constructor() {
        this.categoryDB = new CategoryDB();
        this.mergeEngine = null;
        this.stockLoaded = false;
        this.stockMode = 'github';
        this.customPacks = new Map();
        this.enabledSources = new Set();
        this.categorySelections = new Map();
        this.priorityOrder = [];
        this.mergeMode = 'category';
        this.categoryDbData = null;
        this.userCustomisations = new Map();
        this.userCustomisationsId = 'user-customisations';
        this.customiserGroupFilter = null;
        this.customiserCategoryFilter = null;
        this.categoryFilter = '';
        this.changedOnly = true;
        this.fillGaps = loadState()?.fillGaps ?? true;
        this.savedState = loadState();
    }

    async init() {
        await this.categoryDB.load();
        this.mergeEngine = new MergeEngine(this.categoryDB);
        this.bindEvents();
        this.bindShellEvents();
        this.renderPackList();
        this.stockPromise = this.loadStockFromGitHub();
        this.loadCategoryDb();
        this.renderCustomiserFilters();
        this.restoreCustomisations();
    }

    bindEvents() {
        // Stock source toggle
        document.getElementById('stock-github').addEventListener('change', () => {
            this.stockMode = 'github';
            document.getElementById('stock-upload-area').style.display = 'none';
            document.getElementById('stock-option-github').classList.add('active');
            document.getElementById('stock-option-custom').classList.remove('active');
            this.loadStockFromGitHub();
        });

        document.getElementById('stock-custom').addEventListener('change', () => {
            this.stockMode = 'custom';
            document.getElementById('stock-upload-area').style.display = 'block';
            document.getElementById('stock-option-custom').classList.add('active');
            document.getElementById('stock-option-github').classList.remove('active');
        });

        document.getElementById('stock-file-input').addEventListener('change', (e) => {
            if (e.target.files.length) this.loadStockFromFile(e.target.files[0]);
        });

        document.getElementById('stock-upload-btn').addEventListener('click', () => {
            document.getElementById('stock-file-input').click();
        });

        // Custom pack upload
        document.getElementById('custom-pack-input').addEventListener('change', (e) => {
            for (const file of e.target.files) {
                this.loadCustomPack(file);
            }
            e.target.value = '';
        });

        document.getElementById('custom-upload-btn').addEventListener('click', () => {
            document.getElementById('custom-pack-input').click();
        });

        // Suggest language pack button
        document.getElementById('suggest-pack-btn').addEventListener('click', () => {
            const title = encodeURIComponent('Suggest a language pack');
            const body = encodeURIComponent(
                `**Pack name:** \n**GitHub URL or download link:** \n**What does this pack do?** \n\n**Why should it be added?** \n`
            );
            window.open(`https://github.com/AdamWaldie/ScCompLangPackWaldo/issues/new?title=${title}&body=${body}&labels=suggest-source`, '_blank');
        });

        // Merge buttons download straight away; the install steps sit next to the button.
        document.getElementById('merge-btn').addEventListener('click', () => {
            this.mergeMode = 'category';
            this.doMerge();
        });
        document.getElementById('priority-merge-btn').addEventListener('click', () => {
            this.mergeMode = 'priority';
            this.doMerge();
        });

        // Tab switching
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');

                // Refresh tab-specific content when switching
                if (btn.dataset.tab === 'compare') {
                    this.renderComparePackSelector();
                }
                if (btn.dataset.tab === 'priority') {
                    this.renderPriorityList();
                    this.updatePriorityStats();
                }
                if (btn.dataset.tab === 'customiser') {
                    this.renderMyCustomisations();
                }
            });
        });

        // Category browser search
        const dbSearchInput = document.getElementById('db-search-input');
        let dbSearchTimeout;
        dbSearchInput.addEventListener('input', () => {
            clearTimeout(dbSearchTimeout);
            dbSearchTimeout = setTimeout(() => this.searchCategoryDb(dbSearchInput.value), 200);
        });

        // Compare tab search
        const compareSearchInput = document.getElementById('compare-search-input');
        let compareSearchTimeout;
        compareSearchInput.addEventListener('input', () => {
            clearTimeout(compareSearchTimeout);
            compareSearchTimeout = setTimeout(() => this.searchCompare(compareSearchInput.value), 200);
        });

        // Customiser tab search
        const customiserSearchInput = document.getElementById('customiser-search-input');
        let customiserSearchTimeout;
        customiserSearchInput.addEventListener('input', () => {
            clearTimeout(customiserSearchTimeout);
            customiserSearchTimeout = setTimeout(() => this.searchCustomiser(customiserSearchInput.value), 200);
        });

        // Customiser persistence checkbox
        document.getElementById('customiser-persist').addEventListener('change', (e) => {
            try {
                if (e.target.checked) {
                    this.saveCustomisationsToStorage();
                } else {
                    localStorage.removeItem('pm-user-customisations');
                    localStorage.removeItem('pm-customiser-persist');
                }
                localStorage.setItem('pm-customiser-persist', e.target.checked ? 'true' : '');
            } catch {
                this.toast('This browser blocks storage, so customizations can\'t be remembered');
            }
        });

        // Customiser export/import/clear
        document.getElementById('customiser-export-btn').addEventListener('click', () => this.exportCustomisations());
        document.getElementById('customiser-import-btn').addEventListener('click', () => {
            document.getElementById('customiser-import-input').click();
        });
        document.getElementById('customiser-import-input').addEventListener('change', (e) => {
            if (e.target.files.length) this.importCustomisations(e.target.files[0]);
            e.target.value = '';
        });
        document.getElementById('customiser-clear-btn').addEventListener('click', () => this.clearCustomisations());
    }

    // --- File Age ---

    async fetchFileAge(source) {
        try {
            const response = await fetch(
                `https://api.github.com/repos/${source.repo}/commits?path=${source.path}&per_page=1`
            );
            if (!response.ok) return null;
            const commits = await response.json();
            if (!commits.length) return null;
            return this.formatRelativeAge(new Date(commits[0].commit.committer.date));
        } catch {
            return null;
        }
    }

    formatRelativeAge(date) {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const day = date.getDate();
        const suffix = day === 1 || day === 21 || day === 31 ? 'st'
                     : day === 2 || day === 22 ? 'nd'
                     : day === 3 || day === 23 ? 'rd' : 'th';
        const dateStr = `${months[date.getMonth()]} ${day}${suffix}`;

        const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
        let relative;
        if (seconds < 86400) relative = 'today';
        else {
            const days = Math.floor(seconds / 86400);
            if (days === 1) relative = '1 day ago';
            else if (days < 14) relative = `${days} days ago`;
            else {
                const weeks = Math.floor(days / 7);
                if (weeks === 1) relative = '1 week ago';
                else if (days < 60) relative = `${weeks} weeks ago`;
                else {
                    const mos = Math.floor(days / 30);
                    if (mos === 1) relative = '1 month ago';
                    else if (days < 365) relative = `${mos} months ago`;
                    else {
                        const years = Math.floor(days / 365);
                        relative = years === 1 ? '1 year ago' : `${years} years ago`;
                    }
                }
            }
        }

        return relative === 'today'
            ? `Last updated ${dateStr}, today`
            : `Last updated ${dateStr}, ${relative}`;
    }

    // --- Stock Loading ---

    async loadStockFromGitHub() {
        this.setStockStatus('loading', 'Fetching stock from GitHub...');
        try {
            const [response, age] = await Promise.all([
                fetch(STOCK_SOURCE.url),
                this.fetchFileAge(STOCK_SOURCE)
            ]);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const text = await response.text();
            const data = parseIni(text);
            this.mergeEngine.setStock(data);
            this.stockLoaded = true;
            const ageStr = age ? ` — ${age}` : '';
            const version = [...data].find(([k]) => k.startsWith('Frontend_PU_Version'))?.[1] || '';
            const short = (version.match(/\d+\.\d+(?:\.\d+)?/) || [''])[0];
            this.setStockStatus('loaded', short ? `LIVE ${short}` : `Stock ready`);
            // CIG's menu string often omits the patch number; our version.json has it.
            fetch(STOCK_VERSION_URL).then(r => r.ok ? r.json() : null).then(meta => {
                if (meta?.version) this.setStockStatus('loaded', `LIVE ${meta.version}`);
            }).catch(() => {});
            document.getElementById('stock-status').title = `${version} · ${data.size.toLocaleString()} keys${ageStr}`;
            this.refreshAll();
            this.applyInitialSelections();
        } catch (err) {
            this.setStockStatus('error', `Failed to load stock: ${err.message}`);
            this.stockLoaded = false;
        }
    }

    async loadStockFromFile(file) {
        this.setStockStatus('loading', 'Reading file...');
        try {
            const text = await readFileAsText(file);
            const data = parseIni(text);
            this.mergeEngine.setStock(data);
            this.stockLoaded = true;
            this.setStockStatus('loaded', `Stock loaded: ${data.size.toLocaleString()} keys (${file.name})`);
            this.refreshAll();
        } catch (err) {
            this.setStockStatus('error', `Failed to read file: ${err.message}`);
            this.stockLoaded = false;
        }
    }

    setStockStatus(state, message) {
        const el = document.getElementById('stock-status');
        el.className = `status status-${state}`;
        el.innerHTML = state === 'loading'
            ? `<span class="spinner"></span>${message}`
            : message;
    }

    // --- Language Pack Management ---

    /**
     * Get source definition by ID (for looking up repo/url).
     */
    getSourceDef(sourceId) {
        return LANGUAGE_PACK_SOURCES.find(s => s.id === sourceId) || null;
    }

    renderPackList() {
        const container = document.getElementById('github-packs');
        container.innerHTML = '';
        const savedEnabled = this.savedState?.enabled;

        for (const source of LANGUAGE_PACK_SOURCES) {
            const card = document.createElement('div');
            card.className = 'pack-card';
            card.id = `pack-${source.id}`;
            card.innerHTML = `
                <label class="pack-toggle" title="Use this pack">
                    <input type="checkbox" id="check-${source.id}">
                    <span class="toggle" aria-hidden="true"></span>
                </label>
                <div class="pack-info">
                    <div class="pack-title-row">
                        <span class="pack-name">${source.name}</span>
                        <span class="pack-status" id="status-${source.id}"></span>
                    </div>
                    <div class="pack-desc">${source.description}</div>
                    <div class="pack-meta">
                        <span class="pack-stats" id="stats-${source.id}"></span>
                        <a class="pack-link" href="${source.url}" target="_blank" rel="noopener">View file</a>
                    </div>
                    <div class="pack-actions" id="actions-${source.id}"></div>
                </div>
            `;
            container.appendChild(card);

            const checkbox = card.querySelector(`#check-${source.id}`);
            checkbox.addEventListener('change', () => {
                this.clearActivePreset();
                if (checkbox.checked) {
                    card.classList.add('enabled');
                    this.enableSource(source).then(() => this.saveState());
                } else {
                    card.classList.remove('enabled');
                    this.disableSource(source);
                    this.saveState();
                }
            });
            // Clicking anywhere on the card toggles it (links and buttons keep their own behaviour).
            card.addEventListener('click', (e) => {
                if (e.target.closest('a, button, label, select, input')) return;
                checkbox.click();
            });

            const startEnabled = savedEnabled ? savedEnabled.includes(source.id) : source.defaultEnabled;
            if (startEnabled) {
                checkbox.checked = true;
                card.classList.add('enabled');
                this.enableSource(source);
            }
        }
    }

    enableSource(source) {
        this.pending = this.pending || new Map();
        const promise = this.loadSource(source);
        this.pending.set(source.id, promise);
        return promise;
    }

    async loadSource(source) {
        this.enabledSources.add(source.id);
        const statusEl = document.getElementById(`status-${source.id}`);
        const statsEl = document.getElementById(`stats-${source.id}`);
        const actionsEl = document.getElementById(`actions-${source.id}`);

        statusEl.innerHTML = '<span class="status status-loading"><span class="spinner"></span>Loading</span>';

        try {
            const [response, age] = await Promise.all([
                fetch(source.url),
                this.fetchFileAge(source)
            ]);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const text = await response.text();
            const data = parseIni(text);

            this.mergeEngine.addImport(source.id, data);
            statusEl.innerHTML = `<span class="status status-loaded" title="${age || ''}">${age ? age.replace(/^Last updated [^,]*, /, 'Updated ') : 'Loaded'}</span>`;

            if (this.stockLoaded) {
                const diff = this.mergeEngine.getCategoryDiff(source.id);
                let modifiedCategories = 0;
                let modifiedKeys = 0;
                for (const [, stats] of diff) {
                    if (stats.modified > 0) {
                        modifiedCategories++;
                        modifiedKeys += stats.modified;
                    }
                }
                statsEl.textContent = `${modifiedKeys.toLocaleString()} lines changed · ${modifiedCategories} categories`;
            }

            actionsEl.innerHTML = '';
            const defaultBtn = document.createElement('button');
            defaultBtn.className = 'set-default-btn';
            defaultBtn.type = 'button';
            defaultBtn.textContent = 'Use for every category it changes';
            defaultBtn.addEventListener('click', () => {
                this.clearActivePreset();
                this.setAllToSource(source.id);
                this.saveState();
                this.toast(`${source.name} selected wherever it changes text`);
            });
            actionsEl.appendChild(defaultBtn);

            if (!this.priorityOrder.includes(source.id)) {
                this.priorityOrder.push(source.id);
            }

            this.applyInitialSelections();

            this.renderCategoryTree();
            this.updateMergeButton();
            this.renderPriorityList();
            this.updatePriorityStats();
            this.updatePriorityMergeButton();
        } catch (err) {
            statusEl.innerHTML = `<span class="status status-error" title="${this.escapeHtml(err.message)}">Failed to load</span>`;
            this.enabledSources.delete(source.id);
        }
    }

    disableSource(source) {
        this.enabledSources.delete(source.id);
        this.mergeEngine.removeImport(source.id);
        document.getElementById(`stats-${source.id}`).textContent = '';
        document.getElementById(`status-${source.id}`).innerHTML = '';
        document.getElementById(`actions-${source.id}`).innerHTML = '';

        for (const [cat, src] of this.categorySelections) {
            if (src === source.id) this.categorySelections.delete(cat);
        }
        this.priorityOrder = this.priorityOrder.filter(id => id !== source.id);

        this.renderCategoryTree();
        this.updateMergeButton();
        this.renderPriorityList();
        this.updatePriorityStats();
        this.updatePriorityMergeButton();
    }

    /**
     * Set ALL categories to a given source (where it has modifications).
     */
    /**
     * Once the stock file and packs are in, restore the saved choices, or on a first visit
     * pre-select our own pack so a plain download already gives a working result.
     * Stock and packs can finish loading in any order, so this runs after each of them.
     */
    applyInitialSelections() {
        if (!this.stockLoaded || this.initialSelectionsDone) return;
        const saved = this.savedState?.selections;
        if (saved) {
            for (const [cat, src] of Object.entries(saved)) {
                if (this.mergeEngine.imports.has(src)) this.categorySelections.set(cat, src);
            }
            // Done once every pack the saved choices need has loaded.
            this.initialSelectionsDone = Object.values(saved).every(src => this.mergeEngine.imports.has(src)
                || !this.enabledSources.has(src));
            this.renderCategoryTree();
            this.updateMergeButton();
            return;
        }
        const source = LANGUAGE_PACK_SOURCES.find(s => s.preselect && this.mergeEngine.imports.has(s.id));
        if (!source) return;
        this.initialSelectionsDone = true;
        this.setAllToSource(source.id);
    }

    setAllToSource(sourceId) {
        if (!this.stockLoaded) return;
        const allDiffs = this.mergeEngine.getAllCategoryDiffs();
        const hierarchy = this.categoryDB.getHierarchy();

        for (const group of hierarchy) {
            this.setGroupSelection(group.name, sourceId, allDiffs);
        }

        this.renderCategoryTree();
        this.updateMergeButton();
    }

    async loadCustomPack(file) {
        const id = `custom-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
        try {
            const text = await readFileAsText(file);
            const data = parseIni(text);
            this.mergeEngine.addImport(id, data);
            this.customPacks.set(id, { name: file.name, data });
            this.enabledSources.add(id);
            this.priorityOrder.push(id);
            this.renderCustomPacks();
            this.renderCategoryTree();
            this.updateMergeButton();
            this.renderPriorityList();
            this.updatePriorityStats();
            this.updatePriorityMergeButton();
        } catch (err) {
            console.error('Failed to load custom pack:', err);
        }
    }

    removeCustomPack(id) {
        this.mergeEngine.removeImport(id);
        this.customPacks.delete(id);
        this.enabledSources.delete(id);
        this.priorityOrder = this.priorityOrder.filter(pid => pid !== id);

        for (const [cat, src] of this.categorySelections) {
            if (src === id) this.categorySelections.delete(cat);
        }

        this.renderCustomPacks();
        this.renderCategoryTree();
        this.updateMergeButton();
    }

    renderCustomPacks() {
        const container = document.getElementById('custom-packs');
        container.innerHTML = '';

        for (const [id, pack] of this.customPacks) {
            let statsText = '';
            if (this.stockLoaded) {
                const diff = this.mergeEngine.getCategoryDiff(id);
                let modifiedKeys = 0;
                let modifiedCategories = 0;
                for (const [, stats] of diff) {
                    if (stats.modified > 0) {
                        modifiedCategories++;
                        modifiedKeys += stats.modified;
                    }
                }
                statsText = `${modifiedKeys.toLocaleString()} lines changed · ${modifiedCategories} categories`;
            }

            const card = document.createElement('div');
            card.className = 'custom-pack-card';
            card.innerHTML = `
                <div class="pack-info">
                    <div class="pack-name">${pack.name}</div>
                    <div class="pack-stats">${statsText}</div>
                </div>
                <button class="set-default-btn" data-id="${id}">Use everywhere</button>
                <button class="remove-btn" data-id="${id}">Remove</button>
            `;

            card.querySelector('.remove-btn').addEventListener('click', () => {
                this.removeCustomPack(id);
            });
            card.querySelector('.set-default-btn').addEventListener('click', () => {
                this.setAllToSource(id);
            });

            container.appendChild(card);
        }
    }

    // --- Category Tree ---

    getSourceDisplayName(sourceId) {
        for (const s of LANGUAGE_PACK_SOURCES) {
            if (s.id === sourceId) return s.short || s.name;
        }
        const custom = this.customPacks.get(sourceId);
        if (custom) return custom.name;
        return sourceId;
    }

    setGroupSelection(groupName, sourceId, allDiffs) {
        const hierarchy = this.categoryDB.getHierarchy();
        const group = hierarchy.find(g => g.name === groupName);
        if (!group) return;

        for (const cat of group.categories) {
            if (sourceId) {
                let hasModifications = false;
                for (const [srcName, diffs] of allDiffs) {
                    if (srcName === sourceId) {
                        const catDiff = diffs.get(cat.name);
                        if (catDiff && catDiff.modified > 0) {
                            hasModifications = true;
                            break;
                        }
                    }
                }
                if (hasModifications) {
                    this.categorySelections.set(cat.name, sourceId);
                }
            } else {
                this.categorySelections.delete(cat.name);
            }
        }
    }

    renderCategoryTree() {
        const container = document.getElementById('category-tree');

        if (!this.stockLoaded || this.enabledSources.size === 0) {
            this.lastDiffs = null;
            container.innerHTML = this.stockLoaded
                ? '<div class="category-empty">Switch on a pack in step 1, or pick a preset.</div>'
                : '<div class="category-empty"><span class="spinner"></span>Loading the stock file…</div>';
            return;
        }

        const allDiffs = this.mergeEngine.getAllCategoryDiffs();
        this.lastDiffs = allDiffs;
        const hierarchy = this.categoryDB.getHierarchy();
        const filter = this.categoryFilter.trim().toLowerCase();
        const matches = (text) => !filter || (text || '').toLowerCase().includes(filter);

        container.innerHTML = '';
        let shownGroups = 0;

        for (const group of hierarchy) {
            // Per category: which packs change it, and by how much.
            const catInfo = group.categories.map(cat => {
                const sources = [];
                for (const [sourceName, diffs] of allDiffs) {
                    const d = diffs.get(cat.name);
                    if (d && d.modified > 0) sources.push({ id: sourceName, count: d.modified });
                }
                return { cat, sources, total: sources.reduce((n, x) => n + x.count, 0) };
            });
            const groupSources = new Map();
            for (const { sources } of catInfo) {
                for (const x of sources) groupSources.set(x.id, (groupSources.get(x.id) || 0) + x.count);
            }
            const groupHasMods = groupSources.size > 0;
            const groupMatches = matches(group.name);
            const rows = catInfo.filter(({ cat, total }) =>
                (!this.changedOnly || total > 0) && (groupMatches || matches(cat.name) || matches(cat.description)));
            if (rows.length === 0 || (this.changedOnly && !groupHasMods)) continue;
            shownGroups++;

            const selectedCount = catInfo.filter(({ cat }) => this.categorySelections.has(cat.name)).length;
            const modifiable = catInfo.filter(({ total }) => total > 0);

            const groupEl = document.createElement('div');
            groupEl.className = 'category-group' + (selectedCount ? ' has-selection' : '');

            const expanded = groupHasMods || !!filter;
            const headerEl = document.createElement('div');
            headerEl.className = 'group-header' + (expanded ? ' expanded' : '');
            headerEl.innerHTML = `
                <span class="arrow" aria-hidden="true"><svg viewBox="0 0 24 24" width="14" height="14"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
                <span class="group-name">${this.escapeHtml(group.name)}</span>
                <span class="group-stats">${groupHasMods
                    ? `${selectedCount}/${modifiable.length} chosen`
                    : 'no changes'}</span>`;

            if (groupHasMods) {
                const groupSourceEl = document.createElement('div');
                groupSourceEl.className = 'group-source';
                const groupSelect = document.createElement('select');
                groupSelect.setAttribute('aria-label', `Source for all of ${group.name}`);
                groupSelect.innerHTML = '<option value="">Stock (unchanged)</option>' + [...groupSources]
                    .map(([id, n]) => `<option value="${id}">${this.escapeHtml(this.getSourceDisplayName(id))} · ${n}</option>`).join('');
                const picks = modifiable.map(({ cat }) => this.categorySelections.get(cat.name) || '');
                if (picks.length && picks.every(x => x === picks[0])) groupSelect.value = picks[0];
                else groupSelect.value = picks.some(Boolean) ? '__mixed' : '';
                if (groupSelect.value === '' && picks.some(Boolean)) {
                    groupSelect.insertAdjacentHTML('afterbegin', '<option value="__mixed" disabled>Mixed</option>');
                    groupSelect.value = '__mixed';
                }
                groupSelect.classList.toggle('chosen', picks.some(Boolean));
                groupSelect.addEventListener('click', (e) => e.stopPropagation());
                groupSelect.addEventListener('change', () => {
                    this.clearActivePreset();
                    this.setGroupSelection(group.name, groupSelect.value || '', allDiffs);
                    this.renderCategoryTree();
                    this.updateMergeButton();
                    this.saveState();
                });
                groupSourceEl.appendChild(groupSelect);
                headerEl.appendChild(groupSourceEl);
            }

            const categoriesEl = document.createElement('div');
            categoriesEl.className = 'group-categories' + (expanded ? ' expanded' : '');
            headerEl.addEventListener('click', (e) => {
                if (e.target.closest('select')) return;
                headerEl.classList.toggle('expanded');
                categoriesEl.classList.toggle('expanded');
            });

            for (const { cat, sources, total } of rows) {
                const chosen = this.categorySelections.get(cat.name);
                const row = document.createElement('div');
                row.className = 'category-row' + (chosen ? ' selected' : '');

                const nameEl = document.createElement('div');
                nameEl.className = 'category-name';
                nameEl.textContent = cat.name;
                nameEl.title = cat.description || '';

                const modEl = document.createElement('div');
                modEl.className = 'category-modified' + (total === 0 ? ' none' : '');
                modEl.textContent = total > 0 ? `${total.toLocaleString()} ${total === 1 ? 'line' : 'lines'}` : 'no changes';

                const sourceEl = document.createElement('div');
                sourceEl.className = 'category-source';
                const select = document.createElement('select');
                select.setAttribute('aria-label', `Source for ${cat.name}`);
                if (sources.length > 0) {
                    select.innerHTML = '<option value="">Stock (unchanged)</option>' + sources
                        .map(x => `<option value="${x.id}">${this.escapeHtml(this.getSourceDisplayName(x.id))} · ${x.count}</option>`).join('');
                    if (chosen && sources.some(x => x.id === chosen)) select.value = chosen;
                    select.classList.toggle('chosen', !!select.value);
                    select.addEventListener('change', () => {
                        this.clearActivePreset();
                        if (select.value) this.categorySelections.set(cat.name, select.value);
                        else this.categorySelections.delete(cat.name);
                        this.renderCategoryTree();
                        this.updateMergeButton();
                        this.saveState();
                    });
                } else {
                    select.disabled = true;
                    select.innerHTML = '<option>Stock (no pack changes this)</option>';
                }
                sourceEl.appendChild(select);

                row.append(nameEl, modEl, sourceEl);
                categoriesEl.appendChild(row);
            }

            groupEl.append(headerEl, categoriesEl);
            container.appendChild(groupEl);
        }

        if (shownGroups === 0) {
            container.innerHTML = filter
                ? '<div class="category-empty">No categories match that filter.</div>'
                : '<div class="category-empty">The enabled packs don\'t change anything yet.</div>';
        }
    }

    // --- Merge ---

    updateMergeButton() {
        const btn = document.getElementById('merge-btn');
        const mobileBtn = document.getElementById('mobile-merge-btn');
        const summary = document.getElementById('merge-summary');
        const list = document.getElementById('summary-list');
        const mobileText = document.getElementById('mobile-bar-text');

        const ready = this.stockLoaded && this.categorySelections.size > 0;
        btn.disabled = mobileBtn.disabled = !ready;

        if (this.categorySelections.size === 0) {
            list.innerHTML = '<li class="muted">Nothing selected yet — pick a preset to start.</li>';
            summary.textContent = this.stockLoaded ? 'Your download would be the unchanged stock file.' : '';
            mobileText.textContent = 'Nothing selected';
            return;
        }

        // Lines each pack contributes through the chosen categories.
        const diffs = this.lastDiffs || this.mergeEngine.getAllCategoryDiffs();
        const perSource = new Map();
        for (const [cat, src] of this.categorySelections) {
            const entry = perSource.get(src) || { cats: 0, lines: 0 };
            entry.cats++;
            entry.lines += diffs.get(src)?.get(cat)?.modified || 0;
            perSource.set(src, entry);
        }
        let totalLines = 0;
        list.innerHTML = '';
        for (const [src, { cats, lines }] of perSource) {
            totalLines += lines;
            const li = document.createElement('li');
            li.innerHTML = `
                <span class="dot" aria-hidden="true"></span>
                <span class="summary-name">${this.escapeHtml(this.getSourceDisplayName(src))}</span>
                <span class="summary-meta">${cats} ${cats === 1 ? 'category' : 'categories'} · ${lines.toLocaleString()} lines</span>`;
            list.appendChild(li);
        }
        summary.innerHTML = `<strong>${totalLines.toLocaleString()}</strong> lines changed from stock`;
        mobileText.textContent = `${totalLines.toLocaleString()} lines · ${perSource.size} ${perSource.size === 1 ? 'pack' : 'packs'}`;
    }

    doMerge() {
        if (!this.stockLoaded) return;

        if (this.mergeMode === 'priority') {
            if (this.priorityOrder.length === 0) return;
            const { merged, stats } = this.mergeEngine.mergePriority(this.priorityOrder);
            const content = serializeIni(merged);
            downloadIni(content, 'global.ini');

            const summary = document.getElementById('priority-merge-summary');
            summary.innerHTML = `Downloaded! <strong>${stats.overriddenKeys.toLocaleString()}</strong> keys overridden from <strong>${stats.perSource.length}</strong> ${stats.perSource.length === 1 ? 'pack' : 'packs'} (${stats.totalKeys.toLocaleString()} total keys)`;
        } else {
            if (this.categorySelections.size === 0) return;
            const { merged, stats } = this.mergeEngine.merge(this.categorySelections, { fillGaps: this.fillGaps });
            const content = serializeIni(merged);
            downloadIni(content, 'global.ini');

            this.toast(`global.ini downloaded · ${stats.overriddenKeys.toLocaleString()} lines changed`);
        }
        this.highlightInstall();
    }

    // --- Priority Merge ---

    renderPriorityList() {
        const container = document.getElementById('priority-list');
        if (!container) return;

        // Filter out any sources no longer enabled
        this.priorityOrder = this.priorityOrder.filter(id => this.enabledSources.has(id));

        if (this.priorityOrder.length === 0) {
            container.innerHTML = '<div class="category-empty">Enable at least one language pack above to set priorities.</div>';
            return;
        }

        container.innerHTML = '';

        this.priorityOrder.forEach((sourceId, index) => {
            const sourceDef = this.getSourceDef(sourceId);
            const custom = this.customPacks.get(sourceId);
            const name = sourceDef ? sourceDef.name : (custom ? custom.name : sourceId);
            const desc = sourceDef ? sourceDef.description : 'Custom upload';

            const item = document.createElement('div');
            item.className = 'priority-item';
            item.innerHTML = `
                <span class="priority-number">${index + 1}</span>
                <span class="priority-name">${this.escapeHtml(name)}</span>
                <span class="priority-desc">${this.escapeHtml(desc)}</span>
                <div class="priority-arrows"></div>
            `;

            const arrows = item.querySelector('.priority-arrows');

            const upBtn = document.createElement('button');
            upBtn.textContent = '\u25B2';
            upBtn.title = 'Move up (higher priority)';
            upBtn.disabled = index === 0;
            upBtn.addEventListener('click', () => this.movePriority(index, -1));
            arrows.appendChild(upBtn);

            const downBtn = document.createElement('button');
            downBtn.textContent = '\u25BC';
            downBtn.title = 'Move down (lower priority)';
            downBtn.disabled = index === this.priorityOrder.length - 1;
            downBtn.addEventListener('click', () => this.movePriority(index, 1));
            arrows.appendChild(downBtn);

            container.appendChild(item);
        });
    }

    movePriority(index, direction) {
        const newIndex = index + direction;
        if (newIndex < 0 || newIndex >= this.priorityOrder.length) return;

        const temp = this.priorityOrder[index];
        this.priorityOrder[index] = this.priorityOrder[newIndex];
        this.priorityOrder[newIndex] = temp;

        this.renderPriorityList();
        this.updatePriorityStats();
        this.updatePriorityMergeButton();
    }

    updatePriorityStats() {
        const container = document.getElementById('priority-stats');
        if (!container) return;

        if (!this.stockLoaded || this.priorityOrder.length === 0) {
            container.innerHTML = '<div class="category-empty">Enable packs and set priority order to see merge statistics.</div>';
            return;
        }

        const { overriddenKeys, perSource } = this.mergeEngine.computePriorityStats(this.priorityOrder);

        container.innerHTML = '';

        perSource.forEach((ps, index) => {
            const sourceDef = this.getSourceDef(ps.sourceId);
            const custom = this.customPacks.get(ps.sourceId);
            const name = sourceDef ? sourceDef.name : (custom ? custom.name : ps.sourceId);

            const row = document.createElement('div');
            row.className = 'priority-stat-row';

            let overlapText = '';
            if (ps.overlapped > 0) {
                overlapText = `<span class="stat-overlapped">(${ps.overlapped.toLocaleString()} overlapped by higher priority)</span>`;
            }

            row.innerHTML = `
                <span class="stat-priority">${index + 1}</span>
                <span class="stat-name">${this.escapeHtml(name)}</span>
                <span class="stat-applied">${ps.applied.toLocaleString()} keys applied</span>
                ${overlapText}
            `;

            container.appendChild(row);
        });

        const total = document.createElement('div');
        total.className = 'priority-stat-total';
        total.textContent = `Total: ${overriddenKeys.toLocaleString()} keys changed from stock`;
        container.appendChild(total);
    }

    updatePriorityMergeButton() {
        const btn = document.getElementById('priority-merge-btn');
        const summary = document.getElementById('priority-merge-summary');
        if (!btn || !summary) return;

        const hasOrder = this.priorityOrder.length > 0;
        btn.disabled = !this.stockLoaded || !hasOrder;

        if (!hasOrder) {
            summary.innerHTML = 'Set priority order to merge.';
        } else {
            summary.innerHTML = `<strong>${this.priorityOrder.length}</strong> ${this.priorityOrder.length === 1 ? 'pack' : 'packs'} in priority order &mdash; ready to merge.`;
        }
    }

    // --- Security ---

    /**
     * Escape unsafe characters for HTML rendering.
     */
    escapeHtml(unsafe) {
        return (unsafe || '').toString()
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // --- Category Browser ---

    async loadCategoryDb() {
        try {
            const response = await fetch('data/category_db.json');
            if (!response.ok) return;
            this.categoryDbData = await response.json();
        } catch {
            // Not fatal
        }
    }

    searchCategoryDb(query) {
        const container = document.getElementById('db-results');
        const countEl = document.getElementById('db-search-count');
        const trimmed = query.trim();

        if (!this.categoryDbData) {
            container.innerHTML = '<div class="category-empty">Category database not loaded. Run <code>scripts/build_category_db.py</code> to generate it.</div>';
            countEl.textContent = '';
            return;
        }

        if (trimmed.length < 3) {
            container.innerHTML = '<div class="category-empty">Type at least 3 characters to search.</div>';
            countEl.textContent = '';
            return;
        }

        const lowerQuery = trimmed.toLowerCase();
        const keys = this.categoryDbData.keys;
        const matches = [];
        const MAX_RESULTS = 200;

        const stockData = this.mergeEngine?.stock;

        for (const [key, info] of Object.entries(keys)) {
            if (key.toLowerCase().includes(lowerQuery)) {
                const value = stockData ? (stockData.get(key) || '') : '';
                matches.push({ key, value, ...info });
                if (matches.length >= MAX_RESULTS) break;
            } else if (stockData) {
                const value = stockData.get(key) || '';
                if (value.toLowerCase().includes(lowerQuery)) {
                    matches.push({ key, value, ...info });
                    if (matches.length >= MAX_RESULTS) break;
                }
            }
        }

        countEl.textContent = matches.length >= MAX_RESULTS
            ? `${MAX_RESULTS}+ matches (showing first ${MAX_RESULTS})`
            : `${matches.length} ${matches.length === 1 ? 'match' : 'matches'}`;

        if (matches.length === 0) {
            container.innerHTML = '<div class="category-empty">No keys found matching your search.</div>';
            return;
        }

        const table = document.createElement('table');
        table.className = 'db-table';
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Key</th>
                    <th>Value</th>
                    <th>Category</th>
                    <th>Group</th>
                    <th></th>
                </tr>
            </thead>
        `;

        const tbody = document.createElement('tbody');
        for (const match of matches) {
            const tr = document.createElement('tr');
            const issueTitle = encodeURIComponent(`Category correction: ${match.key}`);
            const issueBody = encodeURIComponent(
                `**Key:** \`${match.key}\`\n**Current category:** ${match.category}\n**Current group:** ${match.group}\n\n**Suggested category:** \n**Reason:** \n`
            );
            const issueUrl = `https://github.com/AdamWaldie/ScCompLangPackWaldo/issues/new?title=${issueTitle}&body=${issueBody}&labels=category-correction`;

            const displayValue = match.value && match.value.length > 80
                ? match.value.substring(0, 80) + '...'
                : (match.value || '');

            tr.innerHTML = `
                <td class="key-cell">${this.escapeHtml(match.key)}</td>
                <td class="value-cell">${this.escapeHtml(displayValue)}</td>
                <td class="cat-cell">${this.escapeHtml(match.category)}</td>
                <td class="group-cell">${this.escapeHtml(match.group)}</td>
                <td class="report-cell"><a href="${issueUrl}" target="_blank" class="report-link" title="Report incorrect category">Report Incorrect Category</a></td>
            `;
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        container.innerHTML = '';
        container.appendChild(table);
    }

    // --- Compare Items ---

    renderComparePackSelector() {
        const container = document.getElementById('compare-packs');
        container.innerHTML = '';

        if (this.enabledSources.size === 0) {
            container.innerHTML = '<span>No packs enabled</span>';
            return;
        }

        for (const sourceId of this.enabledSources) {
            const name = this.getSourceDisplayName(sourceId);
            const label = document.createElement('label');
            label.innerHTML = `<input type="checkbox" value="${sourceId}" checked> ${this.escapeHtml(name)}`;
            label.querySelector('input').addEventListener('change', () => {
                // Re-search with current query
                const query = document.getElementById('compare-search-input').value;
                if (query.trim().length >= 3) this.searchCompare(query);
            });
            container.appendChild(label);
        }
    }

    getSelectedComparePacks() {
        const checkboxes = document.querySelectorAll('#compare-packs input[type="checkbox"]');
        const selected = [];
        for (const cb of checkboxes) {
            if (cb.checked) selected.push(cb.value);
        }
        return selected;
    }

    searchCompare(query) {
        const container = document.getElementById('compare-results');
        const countEl = document.getElementById('compare-search-count');
        const trimmed = query.trim();

        if (!this.stockLoaded) {
            container.innerHTML = '<div class="category-empty">Stock file not loaded yet.</div>';
            countEl.textContent = '';
            return;
        }

        if (this.enabledSources.size === 0) {
            container.innerHTML = '<div class="category-empty">Enable language packs above, then search to compare.</div>';
            countEl.textContent = '';
            return;
        }

        if (trimmed.length < 3) {
            container.innerHTML = '<div class="category-empty">Type at least 3 characters to search.</div>';
            countEl.textContent = '';
            return;
        }

        const selectedPacks = this.getSelectedComparePacks();
        if (selectedPacks.length === 0) {
            container.innerHTML = '<div class="category-empty">Select at least one pack to compare.</div>';
            countEl.textContent = '';
            return;
        }

        const lowerQuery = trimmed.toLowerCase();
        const stockData = this.mergeEngine.stock;
        const matches = [];
        const MAX_RESULTS = 100;

        for (const [key, stockValue] of stockData) {
            if (key.toLowerCase().includes(lowerQuery) || stockValue.toLowerCase().includes(lowerQuery)) {
                matches.push({ key, stockValue });
                if (matches.length >= MAX_RESULTS) break;
            }
        }

        countEl.textContent = matches.length >= MAX_RESULTS
            ? `${MAX_RESULTS}+ matches (showing first ${MAX_RESULTS})`
            : `${matches.length} ${matches.length === 1 ? 'match' : 'matches'}`;

        if (matches.length === 0) {
            container.innerHTML = '<div class="category-empty">No keys found matching your search.</div>';
            return;
        }

        // Build table with dynamic columns
        const table = document.createElement('table');
        table.className = 'compare-table';

        let headerHtml = '<tr><th>Key</th><th>Stock</th>';
        for (const packId of selectedPacks) {
            headerHtml += `<th>${this.getSourceDisplayName(packId)}</th>`;
        }
        headerHtml += '</tr>';
        table.innerHTML = `<thead>${headerHtml}</thead>`;

        const tbody = document.createElement('tbody');
        for (const match of matches) {
            const tr = document.createElement('tr');

            const stockDisplay = match.stockValue.length > 60
                ? match.stockValue.substring(0, 60) + '...'
                : match.stockValue;

            let html = `<td class="key-cell">${this.escapeHtml(match.key)}</td>`;
            html += `<td class="stock-cell">${this.escapeHtml(stockDisplay)}</td>`;

            for (const packId of selectedPacks) {
                const importData = this.mergeEngine.imports.get(packId);
                const importValue = importData ? importData.get(match.key) : undefined;

                if (importValue === undefined || importValue === match.stockValue) {
                    html += '<td class="same-cell">(same)</td>';
                } else {
                    const display = importValue.length > 60
                        ? importValue.substring(0, 60) + '...'
                        : importValue;
                    html += `<td class="modified-cell">${this.escapeHtml(display)}</td>`;
                }
            }

            tr.innerHTML = html;
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        container.innerHTML = '';
        container.appendChild(table);
    }

    // --- Key Customiser ---

    renderCustomiserFilters() {
        const container = document.getElementById('customiser-filters');
        const subContainer = document.getElementById('customiser-sub-filters');
        container.innerHTML = '';
        subContainer.innerHTML = '';

        const hierarchy = this.categoryDB.getHierarchy();
        if (!hierarchy || hierarchy.length === 0) return;

        const rerunSearch = () => {
            const query = document.getElementById('customiser-search-input').value;
            if (query.trim().length >= 3) this.searchCustomiser(query);
        };

        const allChip = document.createElement('button');
        allChip.className = 'filter-chip active';
        allChip.textContent = 'All';
        allChip.addEventListener('click', () => {
            this.customiserGroupFilter = null;
            this.customiserCategoryFilter = null;
            container.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            allChip.classList.add('active');
            subContainer.innerHTML = '';
            rerunSearch();
        });
        container.appendChild(allChip);

        for (const group of hierarchy) {
            const chip = document.createElement('button');
            chip.className = 'filter-chip';
            chip.textContent = group.name;
            chip.addEventListener('click', () => {
                this.customiserGroupFilter = group.name;
                this.customiserCategoryFilter = null;
                container.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                this.renderCustomiserSubFilters(group);
                rerunSearch();
            });
            container.appendChild(chip);
        }
    }

    renderCustomiserSubFilters(group) {
        const subContainer = document.getElementById('customiser-sub-filters');
        subContainer.innerHTML = '';

        if (!group || !group.categories || group.categories.length <= 1) return;

        const rerunSearch = () => {
            const query = document.getElementById('customiser-search-input').value;
            if (query.trim().length >= 3) this.searchCustomiser(query);
        };

        const allChip = document.createElement('button');
        allChip.className = 'filter-chip filter-chip-sub active';
        allChip.textContent = 'All ' + group.name;
        allChip.addEventListener('click', () => {
            this.customiserCategoryFilter = null;
            subContainer.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            allChip.classList.add('active');
            rerunSearch();
        });
        subContainer.appendChild(allChip);

        for (const cat of group.categories) {
            const chip = document.createElement('button');
            chip.className = 'filter-chip filter-chip-sub';
            chip.textContent = cat.name;
            chip.title = cat.description;
            chip.addEventListener('click', () => {
                this.customiserCategoryFilter = cat.name;
                subContainer.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                rerunSearch();
            });
            subContainer.appendChild(chip);
        }
    }

    searchCustomiser(query) {
        const container = document.getElementById('customiser-results');
        const countEl = document.getElementById('customiser-search-count');
        const trimmed = query.trim();

        if (!this.stockLoaded) {
            container.innerHTML = '<div class="category-empty">Stock file not loaded yet.</div>';
            countEl.textContent = '';
            return;
        }

        if (trimmed.length < 3) {
            container.innerHTML = '<div class="category-empty">Type at least 3 characters to search.</div>';
            countEl.textContent = '';
            return;
        }

        const lowerQuery = trimmed.toLowerCase();
        const stockData = this.mergeEngine.stock;
        const matches = [];
        const MAX_RESULTS = 100;
        const groupFilter = this.customiserGroupFilter;
        const categoryFilter = this.customiserCategoryFilter;
        const catKeys = this.categoryDbData ? this.categoryDbData.keys : null;

        for (const [key, stockValue] of stockData) {
            if (key.toLowerCase().includes(lowerQuery) || stockValue.toLowerCase().includes(lowerQuery)) {
                if (catKeys && (categoryFilter || groupFilter)) {
                    const info = catKeys[key];
                    if (!info) continue;
                    if (categoryFilter && info.category !== categoryFilter) continue;
                    if (!categoryFilter && groupFilter && info.group !== groupFilter) continue;
                }
                matches.push({ key, stockValue });
                if (matches.length >= MAX_RESULTS) break;
            }
        }

        const filterLabel = categoryFilter ? ` in ${categoryFilter}` : (groupFilter ? ` in ${groupFilter}` : '');
        countEl.textContent = matches.length >= MAX_RESULTS
            ? `${MAX_RESULTS}+ matches${filterLabel} (showing first ${MAX_RESULTS})`
            : `${matches.length} ${matches.length === 1 ? 'match' : 'matches'}${filterLabel}`;

        if (matches.length === 0) {
            container.innerHTML = `<div class="category-empty">No keys found matching your search${this.escapeHtml(filterLabel)}.</div>`;
            return;
        }

        // Build dynamic columns: Key | Stock | [enabled packs...] | Your Value | Action
        const enabledPacks = [...this.enabledSources].filter(id => id !== this.userCustomisationsId);

        const table = document.createElement('table');
        table.className = 'compare-table customiser-table';

        let headerHtml = '<tr><th>Key</th><th>Stock</th>';
        for (const packId of enabledPacks) {
            headerHtml += `<th>${this.escapeHtml(this.getSourceDisplayName(packId))}</th>`;
        }
        headerHtml += '<th>Your Value</th><th></th></tr>';
        table.innerHTML = `<thead>${headerHtml}</thead>`;

        const tbody = document.createElement('tbody');
        for (const match of matches) {
            const tr = document.createElement('tr');

            const stockDisplay = match.stockValue.length > 60
                ? match.stockValue.substring(0, 60) + '...'
                : match.stockValue;

            let html = `<td class="key-cell">${this.escapeHtml(match.key)}</td>`;
            html += `<td class="stock-cell">${this.escapeHtml(stockDisplay)}</td>`;

            for (const packId of enabledPacks) {
                const importData = this.mergeEngine.imports.get(packId);
                const importValue = importData ? importData.get(match.key) : undefined;

                if (importValue === undefined || importValue === match.stockValue) {
                    html += '<td class="same-cell">(same)</td>';
                } else {
                    const display = importValue.length > 60
                        ? importValue.substring(0, 60) + '...'
                        : importValue;
                    html += `<td class="modified-cell">${this.escapeHtml(display)}</td>`;
                }
            }

            const existingValue = this.userCustomisations.get(match.key) || '';
            html += `<td class="customiser-input-cell"><input type="text" class="customiser-value-input" data-key="${this.escapeHtml(match.key)}" value="${this.escapeHtml(existingValue)}" placeholder="${this.escapeHtml(match.stockValue.substring(0, 40))}"></td>`;
            html += `<td class="customiser-action-cell"><button class="btn customiser-save-btn" data-key="${this.escapeHtml(match.key)}">Save</button></td>`;

            tr.innerHTML = html;
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        container.innerHTML = '';
        container.appendChild(table);

        // Bind save buttons and enter key
        container.querySelectorAll('.customiser-save-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.key;
                const input = container.querySelector(`.customiser-value-input[data-key="${CSS.escape(key)}"]`);
                if (input && input.value.trim()) {
                    this.saveCustomisation(key, input.value.trim());
                    btn.textContent = 'Saved';
                    btn.classList.add('btn-primary');
                    setTimeout(() => { btn.textContent = 'Save'; btn.classList.remove('btn-primary'); }, 1000);
                }
            });
        });

        container.querySelectorAll('.customiser-value-input').forEach(input => {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const key = input.dataset.key;
                    if (input.value.trim()) {
                        this.saveCustomisation(key, input.value.trim());
                        const btn = container.querySelector(`.customiser-save-btn[data-key="${CSS.escape(key)}"]`);
                        if (btn) { btn.textContent = 'Saved'; btn.classList.add('btn-primary'); setTimeout(() => { btn.textContent = 'Save'; btn.classList.remove('btn-primary'); }, 1000); }
                    }
                }
            });
        });
    }

    saveCustomisation(key, value) {
        const stockValue = this.mergeEngine.stock ? this.mergeEngine.stock.get(key) : null;
        if (value === stockValue) {
            this.userCustomisations.delete(key);
        } else {
            this.userCustomisations.set(key, value);
        }
        this.syncUserCustomisations();
    }

    removeCustomisation(key) {
        this.userCustomisations.delete(key);
        this.syncUserCustomisations();
    }

    clearCustomisations() {
        this.userCustomisations.clear();
        this.syncUserCustomisations();
    }

    syncUserCustomisations() {
        const id = this.userCustomisationsId;

        if (this.userCustomisations.size > 0) {
            this.mergeEngine.addImport(id, this.userCustomisations);
            this.customPacks.set(id, { name: 'My Customizations', data: this.userCustomisations });
            if (!this.enabledSources.has(id)) {
                this.enabledSources.add(id);
            }
            if (!this.priorityOrder.includes(id)) {
                this.priorityOrder.push(id);
            }
        } else {
            this.mergeEngine.removeImport(id);
            this.customPacks.delete(id);
            this.enabledSources.delete(id);
            this.priorityOrder = this.priorityOrder.filter(pid => pid !== id);
            for (const [cat, src] of this.categorySelections) {
                if (src === id) this.categorySelections.delete(cat);
            }
        }

        this.renderCustomPacks();
        this.renderCategoryTree();
        this.updateMergeButton();
        this.renderPriorityList();
        this.updatePriorityStats();
        this.updatePriorityMergeButton();
        this.renderMyCustomisations();
        this.updateCustomiserBadge();

        if (document.getElementById('customiser-persist').checked) {
            this.saveCustomisationsToStorage();
        }
    }

    renderMyCustomisations() {
        const container = document.getElementById('customiser-list');
        const countEl = document.getElementById('customiser-count');
        const exportBtn = document.getElementById('customiser-export-btn');
        const clearBtn = document.getElementById('customiser-clear-btn');

        const count = this.userCustomisations.size;
        countEl.textContent = `${count} customization${count !== 1 ? 's' : ''}`;
        exportBtn.disabled = count === 0;
        clearBtn.disabled = count === 0;

        if (count === 0) {
            container.innerHTML = '<div class="category-empty">No customizations yet. Search above and edit key values to get started.</div>';
            return;
        }

        const table = document.createElement('table');
        table.className = 'db-table customiser-my-table';
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Key</th>
                    <th>Stock Value</th>
                    <th>Your Value</th>
                    <th></th>
                </tr>
            </thead>
        `;

        const tbody = document.createElement('tbody');
        const stockData = this.mergeEngine.stock;

        for (const [key, value] of this.userCustomisations) {
            const stockValue = stockData ? (stockData.get(key) || '') : '';
            const stockDisplay = stockValue.length > 50 ? stockValue.substring(0, 50) + '...' : stockValue;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="key-cell">${this.escapeHtml(key)}</td>
                <td class="stock-cell">${this.escapeHtml(stockDisplay)}</td>
                <td class="customiser-input-cell"><input type="text" class="customiser-value-input customiser-my-input" data-key="${this.escapeHtml(key)}" value="${this.escapeHtml(value)}"></td>
                <td class="customiser-action-cell"><button class="btn customiser-remove-btn" data-key="${this.escapeHtml(key)}">Remove</button></td>
            `;
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        container.innerHTML = '';
        container.appendChild(table);

        container.querySelectorAll('.customiser-my-input').forEach(input => {
            const commitEdit = () => {
                const key = input.dataset.key;
                const newValue = input.value.trim();
                if (!newValue) {
                    this.removeCustomisation(key);
                } else if (newValue !== this.userCustomisations.get(key)) {
                    this.saveCustomisation(key, newValue);
                }
            };
            input.addEventListener('blur', commitEdit);
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { input.blur(); }
            });
        });

        container.querySelectorAll('.customiser-remove-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.removeCustomisation(btn.dataset.key);
            });
        });
    }

    updateCustomiserBadge() {
        const badge = document.getElementById('customiser-badge');
        const count = this.userCustomisations.size;
        if (count > 0) {
            badge.textContent = count;
            badge.style.display = '';
        } else {
            badge.style.display = 'none';
        }
    }

    exportCustomisations() {
        if (this.userCustomisations.size === 0) return;
        const content = serializeIni(this.userCustomisations);
        downloadIni(content, 'my-customizations.ini');
    }

    async importCustomisations(file) {
        try {
            const text = await readFileAsText(file);
            const data = parseIni(text);
            for (const [key, value] of data) {
                this.userCustomisations.set(key, value);
            }
            this.syncUserCustomisations();
        } catch (err) {
            console.error('Failed to import customisations:', err);
        }
    }

    saveCustomisationsToStorage() {
        const entries = Array.from(this.userCustomisations.entries());
        try { localStorage.setItem('pm-user-customisations', JSON.stringify(entries)); } catch { /* not persisted */ }
    }

    restoreCustomisations() {
        let persist = null, saved = null;
        try {
            persist = localStorage.getItem('pm-customiser-persist');
            saved = localStorage.getItem('pm-user-customisations');
        } catch { /* storage unavailable */ }
        if (persist === 'true') {
            document.getElementById('customiser-persist').checked = true;
            if (saved) {
                try {
                    const entries = JSON.parse(saved);
                    this.userCustomisations = new Map(entries);
                    this.syncUserCustomisations();
                } catch {
                    // Corrupt data, ignore
                }
            }
        }
    }

    // --- Refresh ---

    // --- Page shell: theme, presets, filters, persistence, helpers ---

    bindShellEvents() {
        document.getElementById('theme-toggle').addEventListener('click', () => {
            const root = document.documentElement;
            const current = root.dataset.theme
                || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
            root.dataset.theme = current === 'dark' ? 'light' : 'dark';
            try { localStorage.setItem('pm-theme', root.dataset.theme); } catch { /* not persisted */ }
        });

        document.querySelectorAll('.preset').forEach(btn => {
            btn.addEventListener('click', () => this.applyPreset(btn.dataset.preset, btn));
        });

        let filterTimeout;
        document.getElementById('category-filter').addEventListener('input', (e) => {
            clearTimeout(filterTimeout);
            filterTimeout = setTimeout(() => { this.categoryFilter = e.target.value; this.renderCategoryTree(); }, 120);
        });
        document.getElementById('changed-only').addEventListener('change', (e) => {
            this.changedOnly = e.target.checked;
            this.renderCategoryTree();
        });
        const fillGaps = document.getElementById('fill-gaps');
        fillGaps.checked = this.fillGaps;
        fillGaps.addEventListener('change', () => {
            this.fillGaps = fillGaps.checked;
            this.saveState();
        });

        document.getElementById('mobile-merge-btn').addEventListener('click', () => {
            document.getElementById('merge-btn').click();
        });
        document.getElementById('usercfg-btn').addEventListener('click', () => this.downloadUserCfg());

        document.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const text = document.getElementById(btn.dataset.copy).textContent;
                try {
                    await navigator.clipboard.writeText(text);
                    this.toast('Copied');
                } catch {
                    this.toast('Copy failed — select the text instead');
                }
            });
        });

        if (this.savedState?.preset) {
            document.querySelector(`.preset[data-preset="${this.savedState.preset}"]`)?.classList.add('active');
        }
    }

    async applyPreset(name, button) {
        const wanted = PRESETS[name] || [];
        const loads = [];
        for (const source of LANGUAGE_PACK_SOURCES) {
            const checkbox = document.getElementById(`check-${source.id}`);
            const card = document.getElementById(`pack-${source.id}`);
            const on = wanted.includes(source.id);
            if (on && !checkbox.checked) {
                checkbox.checked = true;
                card.classList.add('enabled');
                loads.push(this.enableSource(source));
            } else if (!on && checkbox.checked) {
                checkbox.checked = false;
                card.classList.remove('enabled');
                this.disableSource(source);
            } else if (on && this.pending?.has(source.id)) {
                loads.push(this.pending.get(source.id));
            }
        }
        this.categorySelections.clear();
        this.renderCategoryTree();
        this.updateMergeButton();
        await Promise.all(loads);
        if (!this.stockLoaded) await this.stockPromise;

        const [primary, secondary] = wanted;
        if (primary && this.mergeEngine.imports.has(primary)) this.setAllToSource(primary);
        if (secondary && this.mergeEngine.imports.has(secondary)) {
            const diffs = this.mergeEngine.getAllCategoryDiffs();
            for (const group of this.categoryDB.getHierarchy()) {
                if (!COMPONENT_GROUPS.has(group.name)) this.setGroupSelection(group.name, secondary, diffs);
            }
        }
        this.initialSelectionsDone = true;
        this.renderCategoryTree();
        this.updateMergeButton();

        document.querySelectorAll('.preset').forEach(b => b.classList.toggle('active', b === button));
        this.activePreset = name === 'reset' ? null : name;
        this.saveState();
        this.toast(name === 'reset' ? 'Reset to stock' : `Preset applied: ${button.querySelector('.preset-title').textContent}`);
    }

    clearActivePreset() {
        this.activePreset = null;
        document.querySelectorAll('.preset.active').forEach(b => b.classList.remove('active'));
    }

    saveState() {
        const builtIn = new Set(LANGUAGE_PACK_SOURCES.map(s => s.id));
        const selections = {};
        for (const [cat, src] of this.categorySelections) {
            if (builtIn.has(src)) selections[cat] = src;
        }
        this.savedState = {
            enabled: [...this.enabledSources].filter(id => builtIn.has(id)),
            selections,
            preset: this.activePreset || null,
            fillGaps: this.fillGaps,
        };
        storeState(this.savedState);
    }

    downloadUserCfg() {
        const blob = new Blob(['g_language = english\r\n'], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'user.cfg';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        this.toast('user.cfg downloaded');
    }

    highlightInstall() {
        const el = document.getElementById('install');
        el.classList.remove('flash');
        void el.offsetWidth;  // restart the animation
        el.classList.add('flash');
        if (window.innerWidth < 960) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    toast(message) {
        const el = document.getElementById('toast');
        el.textContent = message;
        el.classList.add('visible');
        clearTimeout(this.toastTimer);
        this.toastTimer = setTimeout(() => el.classList.remove('visible'), 2600);
    }

    refreshAll() {
        for (const source of LANGUAGE_PACK_SOURCES) {
            if (this.enabledSources.has(source.id) && this.mergeEngine.imports.has(source.id)) {
                const diff = this.mergeEngine.getCategoryDiff(source.id);
                const statsEl = document.getElementById(`stats-${source.id}`);
                let modifiedCategories = 0;
                let modifiedKeys = 0;
                for (const [, stats] of diff) {
                    if (stats.modified > 0) {
                        modifiedCategories++;
                        modifiedKeys += stats.modified;
                    }
                }
                if (statsEl) {
                    statsEl.textContent = `${modifiedKeys.toLocaleString()} lines changed · ${modifiedCategories} categories`;
                }
            }
        }
        this.renderCustomPacks();
        this.renderCategoryTree();
        this.updateMergeButton();
    }
}

// Boot
document.addEventListener('DOMContentLoaded', () => {
    const app = new PackMergerApp();
    app.init().catch(err => {
        console.error('Pack Merger init failed:', err);
    });
});
