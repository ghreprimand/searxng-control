from searxng_control.searxng_client import SearchOutcome, parse_metrics

SAMPLE = '''# HELP searxng_engines_response_time_total_seconds The average total response time of the engine
# TYPE searxng_engines_response_time_total_seconds gauge
searxng_engines_response_time_total_seconds{engine_name="google cse"} 0.6
searxng_engines_request_count_total{engine_name="google cse"} 12
searxng_engines_request_count_total{engine_name="duckduckgo web"} 11
searxng_engines_reliability_total{engine_name="duckduckgo web"} 90.0
searxng_engines_result_count_total{engine_name="google cse"} 20
'''


def test_parse_metrics():
    m = parse_metrics(SAMPLE)
    assert m["google cse"] == {"total_s": 0.6, "sent": 12.0, "results": 20.0}
    assert m["duckduckgo web"]["reliability"] == 90.0


def test_engines_with_results():
    o = SearchOutcome(True, 10, results=[{"engines": ["a", "b"]}, {"engines": ["a"]}, {"engine": "c"}])
    assert o.engines_with_results == {"a": 2, "b": 1, "c": 1}
