# Final thesis source

This is the final tiered-terminology source snapshot packaged on 5 October 2026. It accompanies the defended bachelor's thesis, not an earlier working draft.

- Main document: `main.tex`.
- Compiler: pdfLaTeX.
- Bibliography: Biber, `biblatex` IEEE style.
- Fonts/packages: declared in `packages.sty`; a complete TeX Live installation is recommended.
- Figures, title page, appendices and bibliography are included.
- No graduation certificate, signatures, examination transcript or reviewer correspondence is included.

Build from this directory:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

If running manually, use pdfLaTeX, Biber, then pdfLaTeX twice. Generated files are ignored by Git. The retained final PDF is [publications/Jahanimajd_Thesis.pdf](../publications/Jahanimajd_Thesis.pdf), 118 pages, SHA-256 `cc087032b8cf6ccee384cd0ce308c73a95acea7d18c884d10407fe5cfb1b52d3`.

This source was extracted from the recorded final source archive, not reconstructed from a PDF. That archive's SHA-256 is `3f4f6ad3039047e752d7fc63cc08521252d61b749516a0217d47eb0c2309aecc`. Different TeX distributions can change pagination and PDF metadata. The frozen PDF remains authoritative for the published dissertation.

Document/media rights are separate from the software license; see [RIGHTS_AND_DATA.md](../RIGHTS_AND_DATA.md).
