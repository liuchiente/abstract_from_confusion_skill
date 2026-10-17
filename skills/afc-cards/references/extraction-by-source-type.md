# Extraction strategy by source type

Read the entry for the source you are about to extract. These are strategies
for finding claims, not a licence to change the Card boundary rule in
`afc-cards/SKILL.md`: one Card is still one independently referenceable claim.

Use the document structure to choose the extraction strategy:

- **Article, manual or study guide:** extract Definitions, Principles, Rules,
  Processes, Conditions, Exceptions, Inputs/Outputs, Methods, Roles,
  Artifacts, Comparisons, Formulas and worked examples. Keep the section heading
  as context. Split claims that can be queried or change independently.
- **Numbered procedures and bullet lists:** preserve order and parent-child
  relations. A procedure can be a `Process` Card; separately queryable steps,
  prerequisites, outputs and exceptions get their own Cards linked by evidence.
- **Tables and matrices:** preserve headers and row/column coordinates as
  Evidence. Derive Cards per independent rule, threshold, mapping or cell group;
  never flatten the whole matrix into one Reference Card. Keep numeric bounds,
  units, operators and labels exact in Evidence.
- **Charts and diagrams:** use extracted text and local OCR first. Treat OCR as
  candidate Evidence, retain confidence and image/page location, and leave it in
  Review when labels, arrows, branches or spatial relationships are uncertain.
  A diagram's relationships may form a Card only when the visual relation is
  supported and recorded.
- **Code and configuration:** use the language-aware parser's symbol, type,
  call and configuration boundaries. Separate what the code does from comments
  that merely describe intent; cite the exact code Evidence for behavioral
  claims.
- **Slides and notes:** keep slide/page boundaries and titles; extract each
  independent claim, and use speaker notes only with their own source location.

For example, the supplied PMP uncertainty-domain PDF has a five-level impact
scale and a probability-impact matrix on PDF page 12 (printed page 368), then a
decision-tree example on PDF page 22 (printed page 378). Represent the scale,
matrix rule, and EMV decision method as separate Cards with evidence to the
relevant text/table/image units. The worked A/B example (`A EMV = 52M`,
`B EMV = 45M`) supports its own example Card; it should not be copied as the
general decision rule. Keep the extracted image and OCR lines as Evidence so a
reviewer can verify branch direction, values and labels against the page.
