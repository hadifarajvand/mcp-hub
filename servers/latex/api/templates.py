"""Starter project templates and insertable snippets."""

from __future__ import annotations

import re

_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def escape_tex(s: str) -> str:
    return re.sub(r"[\\&%$#_{}~^]", lambda m: _SPECIAL[m.group(0)], s)


def _article(title, author):
    return {"main.tex": rf"""\documentclass[11pt,a4paper]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern,amsmath,amssymb,graphicx,booktabs,hyperref}}

\title{{{title}}}
\author{{{author}}}
\date{{\today}}

\begin{{document}}
\maketitle

\begin{{abstract}}
A short summary of the document.
\end{{abstract}}

\section{{Introduction}}\label{{sec:intro}}
Write here. See Section~\ref{{sec:intro}}.

\end{{document}}
"""}


def _report(title, author):
    return {"main.tex": rf"""\documentclass[11pt,a4paper]{{report}}
\usepackage[utf8]{{inputenc}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern,amsmath,graphicx,booktabs,hyperref}}

\title{{{title}}}
\author{{{author}}}
\date{{\today}}

\begin{{document}}
\maketitle
\tableofcontents

\chapter{{Introduction}}\label{{ch:intro}}
Write here.

\end{{document}}
"""}


def _ieee(title, author):
    return {"main.tex": rf"""\documentclass[conference]{{IEEEtran}}
\usepackage[utf8]{{inputenc}}
\usepackage{{amsmath,graphicx,cite}}

\title{{{title}}}
\author{{\IEEEauthorblockN{{{author}}}}}

\begin{{document}}
\maketitle
\begin{{abstract}}
Abstract text.
\end{{abstract}}

\section{{Introduction}}\label{{sec:intro}}
As shown in~\cite{{knuth1984}}, typesetting matters.

\bibliographystyle{{IEEEtran}}
\bibliography{{refs}}
\end{{document}}
""", "refs.bib": """@book{knuth1984,
  author    = {Donald E. Knuth},
  title     = {The {TeXbook}},
  publisher = {Addison-Wesley},
  year      = {1984}
}
"""}


def _beamer(title, author):
    return {"main.tex": rf"""\documentclass{{beamer}}
\usetheme{{Madrid}}
\usepackage[utf8]{{inputenc}}
\title{{{title}}}
\author{{{author}}}
\date{{\today}}

\begin{{document}}
\frame{{\titlepage}}

\begin{{frame}}{{Outline}}
\tableofcontents
\end{{frame}}

\section{{Introduction}}
\begin{{frame}}{{First slide}}
\begin{{itemize}}
  \item Point one
  \item Point two
\end{{itemize}}
\end{{frame}}

\end{{document}}
"""}


def _letter(title, author):
    return {"main.tex": rf"""\documentclass[11pt]{{letter}}
\usepackage[utf8]{{inputenc}}
\signature{{{author}}}
\address{{Your address \\ City}}
\begin{{document}}
\begin{{letter}}{{Recipient \\ Address}}
\opening{{Dear Sir or Madam,}}

{title}

\closing{{Sincerely,}}
\end{{letter}}
\end{{document}}
"""}


def _cv(title, author):
    return {"main.tex": rf"""\documentclass[11pt,a4paper]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage[margin=2cm]{{geometry}}
\usepackage{{enumitem,hyperref,titlesec}}
\pagestyle{{empty}}
\titleformat{{\section}}{{\large\bfseries}}{{}}{{0em}}{{}}[\titlerule]

\begin{{document}}
\begin{{center}}{{\LARGE\bfseries {author}}}\\[2pt] {title} \quad email@example.com\end{{center}}

\section*{{Experience}}
\textbf{{Role}}, Company \hfill 2020--now
\begin{{itemize}}[nosep]
  \item Achievement.
\end{{itemize}}

\section*{{Education}}
\textbf{{Degree}}, University \hfill 2016--2020

\end{{document}}
"""}


TEMPLATES = {"article": _article, "report": _report, "ieee": _ieee, "beamer": _beamer, "letter": _letter, "cv": _cv}


def render_template(name: str, title: str, author: str) -> dict[str, bytes]:
    if name not in TEMPLATES:
        raise KeyError(name)
    return {k: v.encode() for k, v in TEMPLATES[name](escape_tex(title), escape_tex(author)).items()}


SNIPPETS = {
    "figure": "\\begin{figure}[htbp]\n  \\centering\n  \\includegraphics[width=0.8\\linewidth]{FILE}\n  \\caption{CAPTION}\n  \\label{fig:LABEL}\n\\end{figure}\n",
    "table": "\\begin{table}[htbp]\n  \\centering\n  \\caption{CAPTION}\n  \\label{tab:LABEL}\n  \\begin{tabular}{lcr}\n    \\toprule\n    Left & Center & Right \\\\\n    \\midrule\n    a & b & c \\\\\n    \\bottomrule\n  \\end{tabular}\n\\end{table}\n",
    "equation": "\\begin{equation}\n  EXPRESSION\n  \\label{eq:LABEL}\n\\end{equation}\n",
    "align": "\\begin{align}\n  a &= b + c \\\\\n  d &= e\n\\end{align}\n",
    "itemize": "\\begin{itemize}\n  \\item First\n  \\item Second\n\\end{itemize}\n",
    "enumerate": "\\begin{enumerate}\n  \\item First\n  \\item Second\n\\end{enumerate}\n",
    "theorem": "\\begin{theorem}\\label{thm:LABEL}\n  STATEMENT\n\\end{theorem}\n\\begin{proof}\n  PROOF\n\\end{proof}\n",
    "listing": "\\begin{verbatim}\nCODE\n\\end{verbatim}\n",
    "tikz": "\\begin{tikzpicture}\n  \\draw[->] (0,0) -- (2,0) node[right] {$x$};\n  \\draw[->] (0,0) -- (0,2) node[above] {$y$};\n\\end{tikzpicture}\n",
    "algorithm": "\\begin{algorithm}[htbp]\n  \\caption{CAPTION}\\label{alg:LABEL}\n  \\begin{algorithmic}[1]\n    \\Require input\n    \\Ensure output\n    \\State step\n  \\end{algorithmic}\n\\end{algorithm}\n",
    "subfigures": "\\begin{figure}[htbp]\n  \\centering\n  \\begin{subfigure}{0.48\\linewidth}\n    \\includegraphics[width=\\linewidth]{A}\n    \\caption{First}\n  \\end{subfigure}\\hfill\n  \\begin{subfigure}{0.48\\linewidth}\n    \\includegraphics[width=\\linewidth]{B}\n    \\caption{Second}\n  \\end{subfigure}\n  \\caption{CAPTION}\n\\end{figure}\n",
    "bibliography": "\\bibliographystyle{plain}\n\\bibliography{refs}\n",
    "matrix": "\\begin{pmatrix}\n  a & b \\\\\n  c & d\n\\end{pmatrix}\n",
}
SNIPPET_PACKAGES = {"table": ["booktabs"], "algorithm": ["algorithm", "algpseudocode (algorithmicx)"], "subfigures": ["subcaption"],
                    "tikz": ["tikz"], "figure": ["graphicx"], "theorem": ["amsthm"]}
