Thoth corpus — primary source texts for retrieval (RAG phase 2)
================================================================

Drop PLAIN-TEXT (.txt) files of public-domain source material in this folder,
one work per file. The filename becomes the citation shown to Velle, so name
them readably — underscores become spaces:

    the_kybalion.txt              -> "the kybalion"
    hermetica_mead.txt            -> "hermetica mead"
    book_of_the_dead_budge.txt    -> "book of the dead budge"
    kabbalah_unveiled_mathers.txt -> "kabbalah unveiled mathers"

Use PUBLIC-DOMAIN translations. The ancient texts are old, but many modern
translations are still under copyright. Safe, established choices:
    • The Kybalion (Three Initiates, 1908)
    • Thrice-Greatest Hermes / Hermetica — G.R.S. Mead (1906)
    • The Egyptian Book of the Dead — E.A. Wallis Budge (1895)
    • The Kabbalah Unveiled — S.L. MacGregor Mathers (1887)
Project Gutenberg headers/footers are stripped automatically on indexing.

Then, on the machine that can reach your Ollama server:
    ollama pull nomic-embed-text
    python thoth_rag.py build        # writes thoth_index.npz (+ .json)
    python thoth_rag.py query a serpent coiled by dark water   # sanity check

Finally set  thoth_rag_enabled = True  in config.py. In horus_mode, retrieved
passages are appended after the correspondence lexicon. Rebuild the index
whenever you add or change source files.
