# Authentication headline font

`easypaper-headline.woff` is a glyph subset of Noto Sans CJK SC Bold, from the existing `@embedpdf/fonts-sc` package. It contains only the characters used by the authentication headline: “读懂论文。把理解留在原文旁边。”

The derivative family is renamed **EasyPaper Headline** in the name and CFF tables to respect the reserved font name. The original copyright and SIL Open Font License are retained in `OFL.txt` and the font metadata. No other interface text uses this subset. Missing glyphs fall back to the regular interface stack; update the subset if the headline changes.

The subset uses FontTools with name IDs 0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17 retained, all name languages retained, the headline as the text population, and WOFF compression.
