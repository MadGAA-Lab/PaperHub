from paperhub.pipelines.table_figures import _is_hostile


def test_starred_and_x_envs_are_hostile() -> None:
    assert _is_hostile("tabular*", "a & b \\\\")
    assert _is_hostile("tabularx", "a & b \\\\")


def test_plain_tabular_is_not_hostile() -> None:
    assert not _is_hostile("tabular", "a & b & c \\\\ \\midrule x & 1 & 2 \\\\")


def test_multirow_or_makecell_makes_plain_tabular_hostile() -> None:
    assert _is_hostile("tabular", "\\multirow{2}{*}{a} & b \\\\")
    assert _is_hostile("tabular", "\\makecell{a\\\\b} & c \\\\")


def test_multicolumn_alone_is_not_hostile_but_with_cmidrule_is() -> None:
    assert not _is_hostile("tabular", "\\multicolumn{2}{c}{a} \\\\")
    assert _is_hostile("tabular", "\\multicolumn{2}{c}{a} \\\\ \\cmidrule(lr){1-2}")
