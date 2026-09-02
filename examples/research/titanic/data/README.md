# Titanic data provenance

These are the standard `train.csv` and `test.csv` files from Kaggle's
[Titanic - Machine Learning from Disaster](https://www.kaggle.com/c/titanic/data)
competition.

For an authentication-free, reproducible fetch, this example uses the copies
in `minsuk-heo/kaggle-titanic`:

- `train.csv`: <https://raw.githubusercontent.com/minsuk-heo/kaggle-titanic/master/input/train.csv>
- `test.csv`: <https://raw.githubusercontent.com/minsuk-heo/kaggle-titanic/master/input/test.csv>

SHA-256 checksums:

```text
7d118fef8b6ccf7f81111877bc388536f7b1e498a655e3d649d19aaa010e9f6f  train.csv
56023b9948236f3c7a1c9448fcf418b283e109ef177fa8c7e069158dd7dd52b2  test.csv
```

The competition page describes the columns and the train/test split. The
replicated analytical workflow is based on Manav Sehgal's
[Titanic Data Science Solutions](https://www.kaggle.com/code/startupsci/titanic-data-science-solutions),
which Kaggle identifies as an Apache 2.0 licensed notebook.
