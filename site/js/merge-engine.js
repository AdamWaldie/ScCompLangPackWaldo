/**
 * Merge engine for combining multiple global.ini files by category.
 * Takes a stock base + imported language packs + per-category source selections
 * and produces a merged output.
 */

class MergeEngine {
    /**
     * @param {import('./categories.js').CategoryDB} categoryDB
     */
    constructor(categoryDB) {
        this.categoryDB = categoryDB;
        this.stock = null;              // Map<key, value>
        this.imports = new Map();       // Map<sourceName, Map<key, value>>
        this.keyAdders = new Set();     // packs whose keys missing from stock are written too
        this.stockClassification = null; // Map<key, category> — cached
    }

    /**
     * Set the stock (vanilla) global.ini as the base.
     * @param {Map<string, string>} iniMap - Parsed stock INI
     */
    setStock(iniMap) {
        this.stock = iniMap;
        this.stockClassification = this.categoryDB.classifyAll(iniMap.keys());
    }

    /**
     * Add an imported language pack.
     * @param {string} name - Display name / source ID
     * @param {Map<string, string>} iniMap - Parsed INI from this pack
     * @param {{addsKeys?: boolean}} [options] - addsKeys: the pack adds text for keys stock lacks
     *   (other packs' extra keys are usually ones CIG has since removed, so they are left out)
     */
    addImport(name, iniMap, { addsKeys = false } = {}) {
        this.imports.set(name, iniMap);
        if (addsKeys) this.keyAdders.add(name);
        else this.keyAdders.delete(name);
    }

    /**
     * Remove an imported language pack.
     * @param {string} name - Source ID to remove
     */
    removeImport(name) {
        this.imports.delete(name);
        this.keyAdders.delete(name);
    }

    /**
     * Clear all imports.
     */
    clearImports() {
        this.imports.clear();
        this.keyAdders.clear();
    }

    /**
     * Every key to write: the stock keys in order, then keys the given packs add that stock lacks
     * (e.g. text CIG never wrote for "@item_TypeUtilityTurret"; only packs added with addsKeys),
     * each with its stock value (undefined for an added key, so any pack's value counts as a change).
     * @param {string[]} sourceIds - Packs whose added keys to include
     * @returns {Array<[string, string|undefined]>}
     */
    _entries(sourceIds) {
        const entries = [...this.stock];
        const bare = key => key.split(',')[0].trim().toLowerCase();
        const known = new Set([...this.stock.keys()].map(bare));
        for (const id of sourceIds) {
            const importData = this.imports.get(id);
            if (!importData || !this.keyAdders.has(id)) continue;
            for (const key of importData.keys()) {
                if (known.has(bare(key))) continue;
                known.add(bare(key));
                entries.push([key, undefined]);
            }
        }
        return entries;
    }

    /**
     * Category of a key: cached for stock keys, classified on demand for keys only a pack has.
     * @param {string} key
     * @returns {string}
     */
    _category(key) {
        return this.stockClassification.get(key) ?? this.categoryDB.classify(key);
    }

    /**
     * Compute per-category diff counts for an import against stock.
     * Returns which categories have modifications and how many keys differ.
     * @param {string} importName - Source ID
     * @returns {Map<string, {modified: number, total: number}>} Category -> diff stats
     */
    getCategoryDiff(importName) {
        if (!this.stock) throw new Error('Stock not loaded');
        const importData = this.imports.get(importName);
        if (!importData) throw new Error(`Import not found: ${importName}`);

        const diffs = new Map();

        for (const [key, stockValue] of this._entries([importName])) {
            const category = this._category(key);
            if (!diffs.has(category)) {
                diffs.set(category, { modified: 0, total: 0 });
            }
            diffs.get(category).total++;

            const importValue = importData.get(key);
            if (importValue !== undefined && importValue !== stockValue) {
                diffs.get(category).modified++;
            }
        }

        return diffs;
    }

    /**
     * Get diff info for all loaded imports.
     * @returns {Map<string, Map<string, {modified: number, total: number}>>}
     */
    getAllCategoryDiffs() {
        const allDiffs = new Map();
        for (const name of this.imports.keys()) {
            allDiffs.set(name, this.getCategoryDiff(name));
        }
        return allDiffs;
    }

    /**
     * Get the list of source names that have modifications in a given category.
     * @param {string} category - Category name
     * @returns {string[]} Source names with modifications
     */
    getSourcesForCategory(category) {
        const sources = [];
        for (const [name, importData] of this.imports) {
            for (const [key, stockValue] of this._entries([name])) {
                if (this._category(key) !== category) continue;
                const importValue = importData.get(key);
                if (importValue !== undefined && importValue !== stockValue) {
                    sources.push(name);
                    break;
                }
            }
        }
        return sources;
    }

    /**
     * Merge stock + selected category overrides into a final output.
     * @param {Map<string, string>} selections - Map of category name -> source name to use.
     *   Categories not in this map use stock values.
     * @returns {{merged: Map<string, string>, stats: {totalKeys: number, overriddenKeys: number, categoriesOverridden: number}}}
     */
    merge(selections, { fillGaps = false } = {}) {
        if (!this.stock) throw new Error('Stock not loaded');

        const merged = new Map();
        let overriddenKeys = 0;
        const categoriesUsed = new Set();
        // With fillGaps, a line the chosen pack leaves at stock can come from another pack in the build.
        const buildSources = [...new Set(selections.values())].filter(id => this.imports.has(id));

        for (const [key, stockValue] of this._entries(buildSources)) {
            const category = this._category(key);
            const selectedSource = selections.get(category);
            let value = stockValue;

            if (selectedSource && this.imports.has(selectedSource)) {
                const importValue = this.imports.get(selectedSource).get(key);
                if (importValue !== undefined && importValue !== stockValue) {
                    value = importValue;
                } else if (fillGaps) {
                    for (const other of buildSources) {
                        if (other === selectedSource) continue;
                        const otherValue = this.imports.get(other).get(key);
                        if (otherValue !== undefined && otherValue !== stockValue) {
                            value = otherValue;
                            break;
                        }
                    }
                }
            }

            if (value === undefined) continue;  // a key only another pack adds, not chosen here
            if (value !== stockValue) {
                overriddenKeys++;
                categoriesUsed.add(category);
            }
            merged.set(key, value);
        }

        this._applyVersionOverride(merged);

        return {
            merged,
            stats: {
                totalKeys: merged.size,
                overriddenKeys,
                categoriesOverridden: categoriesUsed.size
            }
        };
    }

    /**
     * Priority-based merge: highest-priority pack's changes win, lower priorities fill gaps.
     * @param {string[]} orderedSources - Source IDs in priority order (index 0 = highest)
     * @returns {{merged: Map<string, string>, stats: {totalKeys: number, overriddenKeys: number, perSource: Array<{sourceId: string, applied: number, overlapped: number}>}}}
     */
    mergePriority(orderedSources) {
        if (!this.stock) throw new Error('Stock not loaded');

        const merged = new Map();
        let overriddenKeys = 0;
        const perSource = orderedSources.map(id => ({ sourceId: id, applied: 0, overlapped: 0 }));

        for (const [key, stockValue] of this._entries(orderedSources)) {
            let finalValue = stockValue;
            let claimed = false;

            for (let i = 0; i < orderedSources.length; i++) {
                const sourceId = orderedSources[i];
                const importData = this.imports.get(sourceId);
                if (!importData) continue;

                const importValue = importData.get(key);
                if (importValue !== undefined && importValue !== stockValue) {
                    if (!claimed) {
                        finalValue = importValue;
                        perSource[i].applied++;
                        claimed = true;
                    } else {
                        perSource[i].overlapped++;
                    }
                }
            }

            if (claimed) overriddenKeys++;
            if (finalValue !== undefined) merged.set(key, finalValue);
        }

        this._applyVersionOverride(merged);

        return {
            merged,
            stats: {
                totalKeys: merged.size,
                overriddenKeys,
                perSource
            }
        };
    }

    /**
     * Compute priority merge stats without building the full merged map.
     * @param {string[]} orderedSources - Source IDs in priority order (index 0 = highest)
     * @returns {{overriddenKeys: number, perSource: Array<{sourceId: string, applied: number, overlapped: number}>}}
     */
    computePriorityStats(orderedSources) {
        if (!this.stock) throw new Error('Stock not loaded');

        const perSource = orderedSources.map(id => ({ sourceId: id, applied: 0, overlapped: 0 }));
        let overriddenKeys = 0;

        for (const [key, stockValue] of this._entries(orderedSources)) {
            let claimed = false;

            for (let i = 0; i < orderedSources.length; i++) {
                const sourceId = orderedSources[i];
                const importData = this.imports.get(sourceId);
                if (!importData) continue;

                const importValue = importData.get(key);
                if (importValue !== undefined && importValue !== stockValue) {
                    if (!claimed) {
                        perSource[i].applied++;
                        claimed = true;
                    } else {
                        perSource[i].overlapped++;
                    }
                }
            }

            if (claimed) overriddenKeys++;
        }

        return { overriddenKeys, perSource };
    }

    /**
     * Append the Pack Merger tag to the main-menu version string.
     * @param {Map<string, string>} merged - The merged output map
     */
    _applyVersionOverride(merged) {
        // The key may carry CIG's ",P" flag, so match on the prefix.
        const key = [...this.stock.keys()].find(k => k.split(',')[0] === 'Frontend_PU_Version');
        if (key) {
            merged.set(key, `${this.stock.get(key)} - ScCompLangPackWaldo Pack Merger`);
        }
    }
}

export { MergeEngine };
