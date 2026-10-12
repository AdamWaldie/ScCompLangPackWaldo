/**
 * Pre-populated GitHub source definitions for the Pack Merger.
 * Each source points to a raw.githubusercontent.com URL for a global.ini file.
 */

const GITHUB_RAW_BASE = 'https://raw.githubusercontent.com';

// Stock metadata (exact patch version) published next to the stock file.
const STOCK_VERSION_URL = `${GITHUB_RAW_BASE}/AdamWaldie/ScCompLangPackWaldo/main/stock/LIVE/version.json`;

const STOCK_SOURCE = {
    id: 'stock-waldo',
    name: 'Stock global.ini',
    description: 'Vanilla unmodified global.ini from the current LIVE patch (auto-updated every patch)',
    repo: 'AdamWaldie/ScCompLangPackWaldo',
    branch: 'main',
    path: 'stock/LIVE/global.ini',
    get url() {
        return `${GITHUB_RAW_BASE}/${this.repo}/${this.branch}/${this.path}`;
    },
    defaultEnabled: true
};

const LANGUAGE_PACK_SOURCES = [
    {
        id: 'waldo-remix',
        short: 'Waldo Remix',
        name: 'ScCompLangPackWaldo Remix',
        description: 'Auto-updated every patch: component Class/Size/Grade prefixes (M2A XL-1), missile tracking tags (EM Dominator II Missile), and contract blueprint, reputation and standing info',
        repo: 'AdamWaldie/ScCompLangPackWaldo',
        branch: 'main',
        path: 'dist/LIVE/remix/data/Localization/english/global.ini',
        get url() {
            return `${GITHUB_RAW_BASE}/${this.repo}/${this.branch}/${this.path}`;
        },
        defaultEnabled: true,
        preselect: true,
        // Adds text for item type/port keys CIG left out of global.ini (see scripts/build.py add_ui_text)
        addsKeys: true
    },
    {
        id: 'waldo-classic',
        short: 'Waldo Classic',
        name: 'ScCompLangPackWaldo Classic',
        description: 'Auto-updated every patch: ExoAE-style suffixes (XL-1 Military A), missile tracking tags ([EM] Dominator II Missile), and contract blueprint, reputation and standing info',
        repo: 'AdamWaldie/ScCompLangPackWaldo',
        branch: 'main',
        path: 'dist/LIVE/classic/data/Localization/english/global.ini',
        get url() {
            return `${GITHUB_RAW_BASE}/${this.repo}/${this.branch}/${this.path}`;
        },
        defaultEnabled: false,
        addsKeys: true
    },
    {
        id: 'mrkraken-starstrings',
        short: 'StarStrings',
        name: 'MrKraken StarStrings',
        description: 'Mission text, blueprint pools, commodity fixes, and UI overflow corrections',
        repo: 'MrKraken/StarStrings',
        branch: 'master',
        path: 'src/For_Players/Data/Localization/english/global.ini',
        get url() {
            return `${GITHUB_RAW_BASE}/${this.repo}/${this.branch}/${this.path}`;
        },
        defaultEnabled: false
    },
    {
        id: 'exoae-original',
        short: 'ExoAE',
        name: 'ExoAE ScCompLangPack',
        description: 'Original component naming pack with size/grade info',
        repo: 'ExoAE/ScCompLangPack',
        branch: 'main',
        path: 'ScCompLangPack/data/Localization/english/global.ini',
        get url() {
            return `${GITHUB_RAW_BASE}/${this.repo}/${this.branch}/${this.path}`;
        },
        defaultEnabled: false
    },
    {
        id: 'exoae-remix2',
        short: 'ExoAE Remix2',
        name: 'ExoAE Remix2',
        description: 'ExoAE\'s alternative remix variant for component naming',
        repo: 'ExoAE/ScCompLangPack',
        branch: 'main',
        path: 'ScCompLangPackRemix2/data/Localization/english/global.ini',
        get url() {
            return `${GITHUB_RAW_BASE}/${this.repo}/${this.branch}/${this.path}`;
        },
        defaultEnabled: false
    }
];

export { STOCK_SOURCE, STOCK_VERSION_URL, LANGUAGE_PACK_SOURCES, GITHUB_RAW_BASE };
