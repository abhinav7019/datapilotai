"""
datapilot_tools.py - the analyst's toolbox for DataPilot AI (no Streamlit code, fully testable)
================================================================================================
  quality_report      data-quality score, missing values, duplicates, outliers, type problems
  apply_steps         no-code cleaning / transform steps (dedupe, fill, filter, calculated column...)
  pivot               pivot tables
  ttest / anova / chi_square / correlation_test / normality / ab_test    statistical tests
  linear_regression   multiple linear regression with p-values
  kmeans              customer / data segmentation
  run_sql             read-only SQL on your data (table name: data)
Needs numpy, pandas, scipy.
"""

import ast
import math
import operator
import re
import sqlite3
import time

import numpy as np
import pandas as pd
from scipy import stats

# ======================================================================
# Outliers and data quality
# ======================================================================


def outlier_mask(s, method="iqr", k=1.5):
    """True for values that are outliers. method: 'iqr' (k=1.5 normal, 3 extreme) or 'z' (k=3)."""
    s = pd.to_numeric(s, errors="coerce")
    if method == "z":
        sd = s.std()
        return ((s - s.mean()).abs() / sd > k).fillna(False) if sd else pd.Series(False, index=s.index)
    q1, q3 = s.quantile(.25), s.quantile(.75)
    iqr = q3 - q1
    return ((s < q1 - k * iqr) | (s > q3 + k * iqr)).fillna(False)


def _is_text(s):
    return s.dtype == object or pd.api.types.is_string_dtype(s)


def _looks_numeric(s):
    s = s.dropna().astype(str)
    if len(s) == 0:
        return False
    return pd.to_numeric(s.str.replace(r"[,\s$€£₹%]", "", regex=True), errors="coerce").notna().mean() > .9


def quality_report(df):
    """Return dict(score, grade, columns, outliers, duplicates, issues)."""
    n, m = len(df), len(df.columns)
    if n == 0 or m == 0:
        return dict(score=0, grade="n/a", columns=pd.DataFrame(), outliers=pd.DataFrame(),
                    duplicates=0, issues=["No data."])
    miss = df.isna().sum()
    miss_pct = float(miss.sum()) / (n * m) * 100
    dups = int(df.duplicated().sum())
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    rows = []
    for c in nums:
        mask = outlier_mask(df[c])
        rows.append(dict(Column=c, Outliers=int(mask.sum()), Percent=round(mask.mean() * 100, 2),
                         Skew=round(float(df[c].skew()), 2) if df[c].notna().sum() > 2 else 0.0,
                         Min=df[c].min(), Max=df[c].max()))
    out = pd.DataFrame(rows, columns=["Column", "Outliers", "Percent", "Skew", "Min", "Max"])
    out_rate = float(out["Percent"].mean()) if len(out) else 0.0
    const = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
    as_text = [c for c in df.columns if _is_text(df[c]) and _looks_numeric(df[c])]
    high_card = [c for c in df.columns if _is_text(df[c]) and n > 20 and df[c].nunique() > .9 * n]

    score = 100.0
    score -= min(40, miss_pct * 2)
    score -= min(20, dups / n * 100 * 2)
    score -= min(20, out_rate * 1.5)
    score -= min(10, len(const) * 3 + len(as_text) * 3)
    score = int(max(0, round(score)))
    grade = "Excellent" if score >= 90 else "Good" if score >= 75 else "Fair" if score >= 55 else "Needs work"

    issues = []
    if miss.sum():
        worst = miss.sort_values(ascending=False).head(3)
        issues.append(f"{int(miss.sum()):,} empty cells ({miss_pct:.1f}%). Most in: " +
                      ", ".join(f"{c} ({v:,})" for c, v in worst.items() if v))
    if dups:
        issues.append(f"{dups:,} duplicate rows ({dups / n:.1%}).")
    if len(out) and out["Outliers"].sum():
        top = out.sort_values("Outliers", ascending=False).head(3)
        issues.append("Outliers found in " + ", ".join(f"{r.Column} ({r.Outliers})" for r in top.itertuples()
                                                        if r.Outliers) + ".")
    if const:
        issues.append("Columns with one value only (no information): " + ", ".join(map(str, const)))
    if as_text:
        issues.append("Numbers stored as text: " + ", ".join(map(str, as_text)) + " (convert them to numbers).")
    if high_card:
        issues.append("Almost every value is different in: " + ", ".join(map(str, high_card)) +
                      " (probably an ID or free text).")
    if not issues:
        issues.append("No problems found.")

    cols = pd.DataFrame({
        "Column": df.columns, "Type": [str(t) for t in df.dtypes],
        "Missing": miss.values, "Missing %": (miss.values / n * 100).round(1),
        "Unique": [df[c].nunique(dropna=True) for c in df.columns],
        "Example": [str(df[c].dropna().iloc[0]) if df[c].notna().any() else "" for c in df.columns]})
    return dict(score=score, grade=grade, columns=cols, outliers=out, duplicates=dups, issues=issues)


# ======================================================================
# Safe calculated columns (no eval of arbitrary code)
# ======================================================================
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_FUNCS = {"abs": np.abs, "log": np.log, "log10": np.log10, "sqrt": np.sqrt, "exp": np.exp, "round": np.round}


def safe_calc(df, expr):
    """Evaluate e.g.  [Unit Price] * Quantity * 1.18  on the columns. Only + - * / // % ** and
    abs/log/log10/sqrt/exp/round are allowed."""
    expr = (expr or "").strip()
    if not expr or len(expr) > 300:
        raise ValueError("Type a formula (up to 300 characters).")
    names = {}

    def repl(m):
        key = f"__c{len(names)}__"
        names[key] = m.group(1)
        return key
    text = re.sub(r"\[([^\]]+)\]", repl, expr)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise ValueError("The formula is not valid. Example: [Price] * Quantity")

    def col(name):
        name = names.get(name, name)
        if name not in df.columns:
            raise ValueError(f"Unknown column: {name}")
        return pd.to_numeric(df[name], errors="coerce")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name):
            return col(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (not isinstance(b, (int, float)) or abs(b) > 10):
                raise ValueError("Powers must be a number between -10 and 10.")
            return _BIN[type(node.op)](a, b)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS \
                and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("Only numbers, columns, + - * / % ** and abs/log/sqrt/exp/round are allowed.")

    out = ev(tree)
    if not isinstance(out, pd.Series):
        out = pd.Series(out, index=df.index)
    return out.replace([np.inf, -np.inf], np.nan)


# ======================================================================
# No-code transform steps
# ======================================================================
CMP_OPS = ["=", "!=", ">", ">=", "<", "<=", "contains", "does not contain", "is one of", "is empty", "is not empty"]


def _need(df, *cols):
    for c in cols:
        if c not in df.columns:
            raise ValueError(f"Column '{c}' is not in the data (any more).")


def apply_step(df, st_):
    """Apply one step dict to df. Returns (new_df, note). Raises ValueError with a friendly message."""
    op = st_["op"]
    df = df.copy()
    if op == "drop_duplicates":
        n = len(df)
        df = df.drop_duplicates()
        return df, f"Removed {n - len(df):,} duplicate rows."
    if op == "drop_columns":
        _need(df, *st_["cols"])
        return df.drop(columns=st_["cols"]), "Dropped columns: " + ", ".join(st_["cols"])
    if op == "rename":
        _need(df, st_["old"])
        new = str(st_["new"]).strip()
        if not new or (new in df.columns and new != st_["old"]):
            raise ValueError("Pick a new name that is not empty or already used.")
        return df.rename(columns={st_["old"]: new}), f"Renamed {st_['old']} to {new}."
    if op == "dropna":
        cols = st_["cols"] or list(df.columns)
        _need(df, *cols)
        n = len(df)
        df = df.dropna(subset=cols)
        return df, f"Removed {n - len(df):,} rows with empty values in {', '.join(cols)}."
    if op == "fillna":
        c, how = st_["col"], st_["how"]
        _need(df, c)
        k = int(df[c].isna().sum())
        s = df[c]
        if how in ("mean", "median"):
            s = pd.to_numeric(s, errors="coerce")
            s = s.fillna(s.mean() if how == "mean" else s.median())
        elif how == "mode":
            m = s.mode()
            s = s.fillna(m.iloc[0]) if len(m) else s
        elif how == "zero":
            s = s.fillna(0)
        elif how == "ffill":
            s = s.ffill()
        elif how == "bfill":
            s = s.bfill()
        elif how == "value":
            v = st_.get("value", "")
            if pd.api.types.is_numeric_dtype(s):
                try:
                    v = float(v)
                except ValueError:
                    raise ValueError("This column is numeric: type a number.")
            s = s.fillna(v)
        else:
            raise ValueError("Unknown fill method.")
        df[c] = s
        return df, f"Filled {k:,} empty cells in {c} ({how})."
    if op == "astype":
        c, to = st_["col"], st_["to"]
        _need(df, c)
        if to == "number":
            raw = df[c].astype(str).str.replace(r"[^\d.\-eE]", "", regex=True)
            df[c] = pd.to_numeric(raw.where(df[c].notna()), errors="coerce")
        elif to == "date":
            df[c] = pd.to_datetime(df[c], errors="coerce")
        elif to == "text":
            df[c] = df[c].astype("string").astype(object).where(df[c].notna(), None)
        else:
            raise ValueError("Unknown type.")
        return df, f"Converted {c} to {to}."
    if op == "text":
        c, how = st_["col"], st_["how"]
        _need(df, c)
        s = df[c].astype("string")
        s = {"trim": s.str.strip(), "lower": s.str.lower(), "upper": s.str.upper(),
             "title": s.str.title()}[how]
        df[c] = s.astype(object).where(s.notna(), None)
        return df, f"Text in {c}: {how}."
    if op == "filter":
        c, cmp_, v = st_["col"], st_["cmp"], st_.get("value", "")
        _need(df, c)
        s = df[c]
        if cmp_ == "is empty":
            keep = s.isna()
        elif cmp_ == "is not empty":
            keep = s.notna()
        elif cmp_ in ("contains", "does not contain"):
            hit = s.astype(str).str.contains(re.escape(str(v)), case=False, na=False)
            keep = hit if cmp_ == "contains" else ~hit
        elif cmp_ == "is one of":
            items = [x.strip() for x in str(v).split(",") if x.strip()]
            keep = s.astype(str).isin(items)
        else:
            if pd.api.types.is_datetime64_any_dtype(s):
                v = pd.to_datetime(v, errors="coerce")
                if pd.isna(v):
                    raise ValueError("Type a date like 2026-01-31.")
            elif pd.api.types.is_numeric_dtype(s):
                try:
                    v = float(v)
                except ValueError:
                    raise ValueError("This column is numeric: type a number.")
            else:
                s, v = s.astype(str), str(v)
            keep = {"=": s == v, "!=": s != v, ">": s > v, ">=": s >= v, "<": s < v, "<=": s <= v}[cmp_]
        n = len(df)
        df = df[keep.fillna(False)]
        return df, f"Filter {c} {cmp_} {v}: kept {len(df):,} of {n:,} rows."
    if op == "outliers":
        c = st_["col"]
        _need(df, c)
        mask = outlier_mask(df[c], st_.get("method", "iqr"), float(st_.get("k", 1.5)))
        n = int(mask.sum())
        return df[~mask], f"Removed {n:,} outlier rows from {c}."
    if op == "calc":
        name = str(st_["name"]).strip()
        if not name or name in df.columns:
            raise ValueError("Pick a new column name that is not already used.")
        df[name] = safe_calc(df, st_["expr"])
        return df, f"New column {name} = {st_['expr']}"
    if op == "bin":
        c = st_["col"]
        _need(df, c)
        name = str(st_.get("name") or f"{c} (group)").strip()
        s = pd.to_numeric(df[c], errors="coerce")
        nb = int(st_.get("bins", 4))
        df[name] = pd.qcut(s, nb, duplicates="drop").astype(str) if st_.get("how") == "quantile" \
            else pd.cut(s, nb).astype(str)
        df[name] = df[name].where(s.notna(), None)
        return df, f"Grouped {c} into {nb} bins as {name}."
    if op == "datepart":
        c, part = st_["col"], st_["part"]
        _need(df, c)
        d = pd.to_datetime(df[c], errors="coerce")
        name = f"{c} ({part})"
        df[name] = {"year": d.dt.year, "quarter": d.dt.quarter, "month": d.dt.month,
                    "month name": d.dt.month_name(), "week": d.dt.isocalendar().week.astype("float"),
                    "weekday": d.dt.day_name(), "day": d.dt.day, "hour": d.dt.hour}[part]
        return df, f"Added {name}."
    raise ValueError(f"Unknown step: {op}")


def describe_step(s):
    op = s["op"]
    return {"drop_duplicates": "Remove duplicate rows",
            "drop_columns": "Drop columns: " + ", ".join(s.get("cols", [])),
            "rename": f"Rename {s.get('old')} to {s.get('new')}",
            "dropna": "Remove rows with empty values in " + (", ".join(s.get("cols") or []) or "any column"),
            "fillna": f"Fill empty cells in {s.get('col')} ({s.get('how')})",
            "astype": f"Convert {s.get('col')} to {s.get('to')}",
            "text": f"{s.get('how')} text in {s.get('col')}",
            "filter": f"Keep rows where {s.get('col')} {s.get('cmp')} {s.get('value', '')}",
            "outliers": f"Remove outliers in {s.get('col')}",
            "calc": f"New column {s.get('name')} = {s.get('expr')}",
            "bin": f"Group {s.get('col')} into {s.get('bins')} bins",
            "datepart": f"Add {s.get('part')} of {s.get('col')}"}.get(op, op)


def apply_steps(df, steps):
    """Apply all steps in order. A failing step is skipped and reported. Returns (df, notes, errors)."""
    notes, errors = [], []
    for i, s in enumerate(steps):
        try:
            df, note = apply_step(df, s)
            notes.append(note)
        except Exception as exc:
            errors.append((i, f"Step {i + 1} ({describe_step(s)}) was skipped: {exc}"))
    return df, notes, errors


# ======================================================================
# Pivot
# ======================================================================
def pivot(df, rows, cols, val, agg="sum", totals=True):
    if not rows:
        raise ValueError("Choose at least one row field.")
    if agg == "count":
        t = pd.pivot_table(df, index=rows, columns=cols or None, values=val, aggfunc="count",
                           margins=totals, margins_name="Total", observed=True)
    else:
        d = df.copy()
        d[val] = pd.to_numeric(d[val], errors="coerce")
        t = pd.pivot_table(d, index=rows, columns=cols or None, values=val, aggfunc=agg,
                           margins=totals, margins_name="Total", observed=True)
    return t


# ======================================================================
# Statistical tests
# ======================================================================
def interpret(p, alpha=0.05, what="a difference"):
    if p < alpha:
        return (f"p = {p:.4g} is below {alpha}: the data shows {what} that is unlikely to be chance "
                "(statistically significant).")
    return (f"p = {p:.4g} is not below {alpha}: the data does not give enough evidence of {what}. "
            "This does not prove there is none.")


def _clean(x):
    return pd.to_numeric(pd.Series(x), errors="coerce").dropna().astype(float).values


def ttest(a, b, paired=False, alpha=0.05):
    a, b = _clean(a), _clean(b)
    if paired:
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
    if len(a) < 2 or len(b) < 2:
        raise ValueError("Each group needs at least 2 values.")
    if paired:
        r = stats.ttest_rel(a, b)
        d = a - b
        se = d.std(ddof=1) / math.sqrt(len(d))
        dfree = len(d) - 1
        diff = d.mean()
        sd = d.std(ddof=1)
        name = "Paired t-test"
    else:
        r = stats.ttest_ind(a, b, equal_var=False)
        va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
        se = math.sqrt(va + vb)
        dfree = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1)) if (va + vb) else len(a) + len(b) - 2
        diff = a.mean() - b.mean()
        sp = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
        sd = sp
        name = "Welch's t-test"
    tcrit = stats.t.ppf(1 - alpha / 2, dfree)
    return dict(test=name, statistic=float(r.statistic), p=float(r.pvalue), n_a=len(a), n_b=len(b),
                mean_a=float(a.mean()), mean_b=float(b.mean()), diff=float(diff),
                ci=(float(diff - tcrit * se), float(diff + tcrit * se)),
                effect_name="Cohen's d", effect=float(diff / sd) if sd else 0.0,
                text=interpret(float(r.pvalue), alpha, "a difference between the group averages"))


def mann_whitney(a, b, alpha=0.05):
    a, b = _clean(a), _clean(b)
    if len(a) < 2 or len(b) < 2:
        raise ValueError("Each group needs at least 2 values.")
    r = stats.mannwhitneyu(a, b, alternative="two-sided")
    rbc = 1 - 2 * r.statistic / (len(a) * len(b))
    return dict(test="Mann-Whitney U (no normality needed)", statistic=float(r.statistic), p=float(r.pvalue),
                n_a=len(a), n_b=len(b), median_a=float(np.median(a)), median_b=float(np.median(b)),
                effect_name="Rank-biserial r", effect=float(rbc),
                text=interpret(float(r.pvalue), alpha, "a difference between the groups"))


def anova(groups, alpha=0.05):
    """groups: dict name -> values. One-way ANOVA + Kruskal-Wallis backup."""
    g = {k: _clean(v) for k, v in groups.items()}
    g = {k: v for k, v in g.items() if len(v) >= 2}
    if len(g) < 2:
        raise ValueError("Need at least 2 groups with 2 or more values.")
    f = stats.f_oneway(*g.values())
    allv = np.concatenate(list(g.values()))
    gm = allv.mean()
    ssb = sum(len(v) * (v.mean() - gm) ** 2 for v in g.values())
    sst = ((allv - gm) ** 2).sum()
    kw = stats.kruskal(*g.values())
    tbl = pd.DataFrame({"Group": list(g), "N": [len(v) for v in g.values()],
                        "Mean": [v.mean() for v in g.values()], "Std": [v.std(ddof=1) for v in g.values()]})
    return dict(test="One-way ANOVA", statistic=float(f.statistic), p=float(f.pvalue),
                effect_name="Eta squared", effect=float(ssb / sst) if sst else 0.0, table=tbl,
                kruskal_p=float(kw.pvalue),
                text=interpret(float(f.pvalue), alpha, "a difference between group averages"))


def chi_square(df, a, b, alpha=0.05):
    ct = pd.crosstab(df[a], df[b])
    if ct.shape[0] < 2 or ct.shape[1] < 2:
        raise ValueError("Both columns need at least 2 different values.")
    chi2, p, dof, exp = stats.chi2_contingency(ct)
    n = ct.values.sum()
    v = math.sqrt(chi2 / (n * (min(ct.shape) - 1))) if n else 0.0
    return dict(test="Chi-square test of independence", statistic=float(chi2), p=float(p), dof=int(dof),
                effect_name="Cramer's V", effect=float(v), table=ct,
                warning=("Some expected counts are below 5, so this result is less reliable."
                         if (exp < 5).any() else ""),
                text=interpret(float(p), alpha, "a link between the two columns"))


def correlation_test(x, y, method="pearson", alpha=0.05):
    d = pd.DataFrame({"x": pd.to_numeric(pd.Series(x).reset_index(drop=True), errors="coerce"),
                      "y": pd.to_numeric(pd.Series(y).reset_index(drop=True), errors="coerce")}).dropna()
    if len(d) < 4:
        raise ValueError("Need at least 4 complete pairs.")
    fn = {"pearson": stats.pearsonr, "spearman": stats.spearmanr, "kendall": stats.kendalltau}[method]
    r, p = fn(d["x"], d["y"])
    ci = None
    if method == "pearson" and abs(r) < 1:
        z, se = np.arctanh(r), 1 / math.sqrt(len(d) - 3)
        zc = stats.norm.ppf(1 - alpha / 2)
        ci = (float(np.tanh(z - zc * se)), float(np.tanh(z + zc * se)))
    strength = "very weak" if abs(r) < .2 else "weak" if abs(r) < .4 else "moderate" if abs(r) < .6 \
        else "strong" if abs(r) < .8 else "very strong"
    return dict(test=f"{method.title()} correlation", statistic=float(r), p=float(p), n=len(d), ci=ci,
                strength=f"{strength} {'positive' if r > 0 else 'negative'}",
                text=interpret(float(p), alpha, "a relationship") +
                     f" The relationship is {strength} ({'positive' if r > 0 else 'negative'}), r = {r:.3f}. "
                     "Correlation is not causation.")


def normality(x, alpha=0.05):
    v = _clean(x)
    if len(v) < 3:
        raise ValueError("Need at least 3 values.")
    sample = v if len(v) <= 5000 else np.random.default_rng(0).choice(v, 5000, replace=False)
    r = stats.shapiro(sample)
    return dict(test="Shapiro-Wilk normality test", statistic=float(r.statistic), p=float(r.pvalue), n=len(v),
                skew=float(stats.skew(v)), kurtosis=float(stats.kurtosis(v)),
                text=("The values look roughly normal (p >= %s)." % alpha if r.pvalue >= alpha else
                      "The values are probably NOT normally distributed (p < %s). Prefer medians and "
                      "non-parametric tests." % alpha))


def ab_test(conv_a, n_a, conv_b, n_b, alpha=0.05):
    """Two-proportion z-test (A/B test on conversion)."""
    if min(n_a, n_b) < 1 or conv_a > n_a or conv_b > n_b or min(conv_a, conv_b) < 0:
        raise ValueError("Conversions must be between 0 and the number of visitors.")
    pa, pb = conv_a / n_a, conv_b / n_b
    pool = (conv_a + conv_b) / (n_a + n_b)
    se0 = math.sqrt(pool * (1 - pool) * (1 / n_a + 1 / n_b))
    z = (pb - pa) / se0 if se0 else 0.0
    p = float(2 * stats.norm.sf(abs(z)))
    se = math.sqrt(pa * (1 - pa) / n_a + pb * (1 - pb) / n_b)
    zc = stats.norm.ppf(1 - alpha / 2)
    return dict(test="Two-proportion z-test (A/B)", rate_a=pa, rate_b=pb, diff=pb - pa,
                lift=(pb / pa - 1) if pa else float("nan"), z=float(z), p=p,
                ci=(float(pb - pa - zc * se), float(pb - pa + zc * se)),
                text=interpret(p, alpha, "a real difference between A and B"))


def ab_sample_size(base_rate, min_lift, alpha=0.05, power=0.8):
    """Visitors needed PER variant to detect a relative lift (e.g. 0.1 = +10%)."""
    p1, p2 = base_rate, base_rate * (1 + min_lift)
    if not (0 < p1 < 1 and 0 < p2 < 1):
        raise ValueError("Rates must stay between 0% and 100%.")
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    pb = (p1 + p2) / 2
    n = ((za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / (p2 - p1) ** 2
    return int(math.ceil(n))


# ======================================================================
# Regression
# ======================================================================
def linear_regression(df, y, xs, max_levels=12):
    if not xs:
        raise ValueError("Choose at least one input column.")
    d = df[[y] + list(xs)].copy()
    d[y] = pd.to_numeric(d[y], errors="coerce")
    num_cols, cat_cols = [], []
    for c in xs:
        if pd.api.types.is_numeric_dtype(d[c]) and not pd.api.types.is_bool_dtype(d[c]):
            num_cols.append(c)
        else:
            if d[c].nunique(dropna=True) > max_levels:
                raise ValueError(f"'{c}' has more than {max_levels} different values. Pick a column with fewer.")
            cat_cols.append(c)
    d = d.dropna()
    levels = {c: sorted(d[c].astype(str).unique()) for c in cat_cols}
    X = d[num_cols].astype(float).copy()
    for c in cat_cols:
        for lv in levels[c][1:]:                                  # first level is the baseline
            X[f"{c} = {lv}"] = (d[c].astype(str) == lv).astype(float)
    n, p = len(X), X.shape[1]
    if n < p + 3:
        raise ValueError(f"Not enough rows ({n}) for {p} inputs.")
    X1 = np.column_stack([np.ones(n), X.values])
    yv = d[y].values.astype(float)
    beta = np.linalg.lstsq(X1, yv, rcond=None)[0]
    fit = X1 @ beta
    res = yv - fit
    sse, sst = float((res ** 2).sum()), float(((yv - yv.mean()) ** 2).sum())
    dof = n - p - 1
    sigma2 = sse / dof
    se = np.sqrt(np.diag(sigma2 * np.linalg.pinv(X1.T @ X1)))
    t = beta / np.where(se == 0, np.nan, se)
    pv = 2 * stats.t.sf(np.abs(t), dof)
    r2 = 1 - sse / sst if sst else 0.0
    coefs = pd.DataFrame({"Term": ["Intercept"] + list(X.columns), "Coefficient": beta, "Std error": se,
                          "t": t, "p-value": pv})
    return dict(coefs=coefs, r2=float(r2), adj_r2=float(1 - (1 - r2) * (n - 1) / dof), n=n,
                rmse=math.sqrt(sse / n), mae=float(np.abs(res).mean()), fitted=fit, resid=res, actual=yv,
                index=d.index, num_cols=num_cols, cat_cols=cat_cols, levels=levels, beta=beta,
                columns=list(X.columns), y=y)


def predict(model, row):
    """row: dict column -> value. Returns the predicted value."""
    x = [1.0] + [float(row[c]) for c in model["num_cols"]]
    for c in model["cat_cols"]:
        for lv in model["levels"][c][1:]:
            x.append(1.0 if str(row[c]) == lv else 0.0)
    return float(np.dot(model["beta"], x))


# ======================================================================
# Clustering (k-means, numpy only)
# ======================================================================
def standardize(X):
    X = np.asarray(X, dtype=float)
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1
    return (X - mu) / sd


def kmeans(X, k, n_init=5, iters=100, seed=0):
    X = np.asarray(X, dtype=float)
    n = len(X)
    if k < 2 or k > n:
        raise ValueError("k must be between 2 and the number of rows.")
    best = None
    for init in range(n_init):
        rng = np.random.default_rng(seed + init)
        centers = [X[rng.integers(n)]]
        for _ in range(k - 1):                                    # k-means++ start
            d2 = np.min(((X[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
            centers.append(X[rng.choice(n, p=d2 / d2.sum())] if d2.sum() else X[rng.integers(n)])
        C = np.array(centers)
        for _ in range(iters):
            d2 = ((X[:, None, :] - C[None]) ** 2).sum(-1)
            lab = d2.argmin(1)
            newC = np.array([X[lab == j].mean(0) if (lab == j).any() else X[rng.integers(n)] for j in range(k)])
            if np.allclose(newC, C):
                break
            C = newC
        d2 = ((X[:, None, :] - C[None]) ** 2).sum(-1)
        lab = d2.argmin(1)
        inertia = float(d2[np.arange(n), lab].sum())
        if best is None or inertia < best[0]:
            best = (inertia, lab, C)
    return dict(inertia=best[0], labels=best[1], centers=best[2])


def silhouette(X, labels, max_n=1500, seed=0):
    X = np.asarray(X, dtype=float)
    if len(X) > max_n:
        idx = np.random.default_rng(seed).choice(len(X), max_n, replace=False)
        X, labels = X[idx], labels[idx]
    if len(set(labels)) < 2:
        return 0.0
    D = np.sqrt(((X[:, None, :] - X[None]) ** 2).sum(-1))
    s = []
    for i in range(len(X)):
        same = labels == labels[i]
        if same.sum() <= 1:
            s.append(0.0)
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, labels == lbl].mean() for lbl in set(labels) if lbl != labels[i])
        s.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return float(np.mean(s))


# ======================================================================
# Read-only SQL on the data
# ======================================================================
_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def run_sql(df, query, limit=10000, timeout=5.0):
    """Run ONE read-only SELECT on the data (table name: data). Returns a DataFrame."""
    q = (query or "").strip().rstrip(";").strip()
    if not q:
        raise ValueError("Type a SQL query, for example:  SELECT * FROM data LIMIT 10")
    if ";" in q:
        raise ValueError("Only one statement at a time (remove the extra ';').")
    if not re.match(r"^(select|with)\b", q, re.I):
        raise ValueError("Only SELECT queries are allowed.")
    con = sqlite3.connect(":memory:")
    try:
        d = df.copy()
        for c in d.columns:
            if pd.api.types.is_datetime64_any_dtype(d[c]):
                d[c] = d[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        d.to_sql("data", con, index=False)
        con.set_authorizer(lambda action, a1, a2, db, src: sqlite3.SQLITE_OK if action in _ALLOWED
                           else sqlite3.SQLITE_DENY)
        t0 = time.time()

        def tick():
            return 1 if time.time() - t0 > timeout else 0
        con.set_progress_handler(tick, 10000)
        try:
            out = pd.read_sql_query(q, con)
        except Exception as exc:
            msg = str(exc)
            if "interrupted" in msg.lower():
                raise ValueError(f"The query took longer than {timeout:.0f} seconds and was stopped.")
            if "not authorized" in msg.lower():
                raise ValueError("Only reading data is allowed.")
            raise ValueError(msg)
        return out.head(limit)
    finally:
        con.close()
