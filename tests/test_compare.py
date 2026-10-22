from eval.compare import results_match as rm


def test_exact_and_float_tolerance():
    assert rm([[1, 2.0]], [[1, 2.004]], False)[0]
    assert not rm([[1, 2.0]], [[1, 2.5]], False)[0]


def test_extra_columns_and_order_of_columns_tolerated():
    assert rm([["SP", 10]], [[10, "SP", 99]], False)[0]


def test_unordered_vs_ordered():
    assert rm([["a", 1], ["b", 2]], [["b", 2], ["a", 1]], False)[0]
    assert not rm([["a", 1], ["b", 2]], [["b", 2], ["a", 1]], True)[0]


def test_row_count_mismatch_and_too_few_columns():
    assert not rm([[1], [2]], [[1]], False)[0]
    assert not rm([[1, 2]], [[1]], False)[0]


def test_midnight_timestamp_equals_date():
    assert rm([["2017-11-01"]], [["2017-11-01T00:00:00"]], True)[0]


def test_wrong_value_with_right_shape_fails():
    assert not rm([[13221498.11]], [[13813828.71]], False)[0]   # the join fan-out answer


def test_year_month_string_equals_first_of_month():
    assert rm([["2017-01-01", 800]], [["2017-01", 800]], True)[0]
    assert not rm([["2017-01-01", 800]], [["2017-02", 800]], True)[0]


def test_numeric_only_ignores_label_spelling():
    ref, got = [[False, 4.29], [True, 2.57]], [["late", 2.57], ["on_time", 4.29]]
    assert not rm(ref, got, False)[0]
    assert rm(ref, got, False, numeric_only=True)[0]
    assert not rm(ref, [["late", 2.57], ["on_time", 3.0]], False, numeric_only=True)[0]
