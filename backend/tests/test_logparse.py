from searxng_control.logparse import Event, LogParser, Startup

NET = "2026-10-05 12:22:47,248 WARNING:searx.network.mojeek: HTTP Request failed: GET https://www.mojeek.com/search?q=tokio+select+macro&safe=0"
CTX = ("2026-10-05 12:22:47,305 WARNING:searx.engines.mojeek: ErrorContext('searx/search/processors/online.py', 211, "
       "'response = req(params[\"url\"], **request_args)  # pyright: ignore[reportArgumentType]', "
       "'searx.exceptions.SearxEngineAccessDeniedException', None, ('HTTP error 403 (suspended_time=1800)',)) False")


def test_access_denied_with_host_and_suspension():
    p = LogParser()
    assert p.parse(100.0, NET) is None
    ev = p.parse(100.05, CTX)
    assert isinstance(ev, Event)
    assert ev.engine == "mojeek"
    assert ev.kind == "blocked"
    assert ev.host == "www.mojeek.com"
    assert ev.suspended_s == 1800
    assert "tokio" not in (ev.detail or "")  # never keep queries
    assert ev.detail == "SearxEngineAccessDeniedException: HTTP error 403 (suspended_time=1800)"


def test_engine_names_with_spaces_and_kinds():
    p = LogParser()
    cases = {
        "2026-10-05 12:07:32,386 WARNING:searx.engines.duckduckgo images: ErrorContext('searx/engines/duckduckgo.py', 477, "
        "'raise SearxEngineCaptchaException(...)', 'searx.exceptions.SearxEngineCaptchaException', None, ('CAPTCHA (wt-wt) (suspended_time=0)',)) False": ("duckduckgo images", "captcha"),
        "2026-10-05 12:07:33,326 WARNING:searx.engines.brave: ErrorContext('searx/search/processors/online.py', 207, 'x', "
        "'searx.exceptions.SearxEngineTooManyRequestsException', None, ('Too many request (suspended_time=180)',)) False": ("brave", "rate_limited"),
        "2026-10-05 12:07:34,596 WARNING:searx.engines.startpage: ErrorContext('searx/engines/startpage.py', 409, "
        "'results_json = loads(results_raw)', 'json.decoder.JSONDecodeError', None, ('Extra data',)) False": ("startpage", "parse_error"),
        "2026-10-05 12:07:35,596 WARNING:searx.engines.startpage: ErrorContext('searx/engines/startpage.py', 193, 'x', "
        "'searx.exceptions.SearxEngineCaptchaException', None, ('startpage: Anubis difficulty too high (suspended_time=1800)',)) False": ("startpage", "challenge"),
        "2026-10-05 12:22:48,003 ERROR:searx.engines.privacywall: engine timeout": ("privacywall", "timeout"),
    }
    for i, (line, (engine, kind)) in enumerate(cases.items()):
        ev = p.parse(200.0 + i * 5, line)
        assert isinstance(ev, Event), line
        assert (ev.engine, ev.kind) == (engine, kind)


def test_startup_and_noise():
    p = LogParser()
    st = p.parse(1.0, "SearXNG 2026.10.4-d48c4b555")
    assert isinstance(st, Startup) and st.version == "2026.10.4-d48c4b555"
    assert p.parse(2.0, "2026-10-05 12:22:18,800 ERROR:searx.botdetection: X-Forwarded-For nor X-Real-IP header is set!") is None
    assert p.parse(3.0, "[INFO] Started worker-1") is None
    load = p.parse(4.0, "2026-10-05 12:22:19,037 ERROR:searx.engines: (PID 883) ahmia: can't register engine (loading engine failed)")
    assert isinstance(load, Event) and load.kind == "load_error" and load.engine == "ahmia"


def test_dedupe_same_instant():
    p = LogParser()
    line = "2026-10-05 12:22:48,003 ERROR:searx.engines.privacywall: engine timeout"
    assert p.parse(10.0, line) is not None
    assert p.parse(10.2, line) is None
    assert p.parse(12.0, line) is not None
