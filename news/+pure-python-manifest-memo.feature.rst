The pure-Python resolver backend now keeps parsed package manifests in
memory for the duration of a resolve instead of re-reading and re-parsing
them from the on-disk cache on every backtracking step, which dominated
resolve time on large dependency sets.
