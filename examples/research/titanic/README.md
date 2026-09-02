# Titanic PMD research replication

This example recreates the structure of a strong Kaggle notebook as a
dependency-aware PMD document. It performs data auditing, EDA, deterministic
feature engineering, stratified cross-validation, model selection, final
training, and Kaggle submission generation.

Run from the repository root:

```powershell
pmd check examples/research/titanic/titanic-research.pmd --graph
pmd run examples/research/titanic/titanic-research.pmd --fresh --verbose
pmd test examples/research/titanic/titanic-research.pmd --fresh --verbose
pmd render examples/research/titanic/titanic-research.pmd --to html --with-tests --fresh --out pmd-outputs/titanic-report.html
```

The notebook declares `python` as its engine because its scientific packages
are not project dependencies. The selected interpreter must provide:

```text
pandas
matplotlib
scikit-learn
```
