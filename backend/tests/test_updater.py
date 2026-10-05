from searxng_control.docker_api import split_ref
from searxng_control.updater import build_create_body

OLD_IMAGE = {"Config": {"Env": ["PATH=/usr/bin", "__SEARXNG_VERSION=2026.10.2-aaa", "GRANIAN_PORT=8080"],
                        "Entrypoint": ["/entrypoint.sh"], "Cmd": None,
                        "Labels": {"org.opencontainers.image.version": "2026.10.2-aaa"},
                        "Volumes": {"/etc/searxng": {}}, "ExposedPorts": {"8080/tcp": {}}}}
NEW_IMAGE = {"Config": {"Env": ["PATH=/usr/bin", "__SEARXNG_VERSION=2026.10.4-bbb", "GRANIAN_PORT=8080"],
                        "Entrypoint": ["/entrypoint.sh"], "Labels": {"org.opencontainers.image.version": "2026.10.4-bbb"}}}
CONTAINER = {
    "Id": "0123456789abcdef",
    "Config": {"Hostname": "0123456789ab", "Image": "searxng/searxng:latest",
               "Env": ["PATH=/usr/bin", "__SEARXNG_VERSION=2026.10.2-aaa", "GRANIAN_PORT=8080", "TZ=Europe/Berlin"],
               "Entrypoint": ["/entrypoint.sh"], "Cmd": None,
               "Labels": {"org.opencontainers.image.version": "2026.10.2-aaa", "com.docker.compose.service": "searxng"},
               "Volumes": {"/etc/searxng": {}}, "ExposedPorts": {"8080/tcp": {}}},
    "HostConfig": {"Binds": ["/srv/searxng:/etc/searxng"], "NetworkMode": "search_default",
                   "RestartPolicy": {"Name": "unless-stopped"}},
    "NetworkSettings": {"Networks": {"search_default": {"Aliases": ["searxng", "0123456789ab"], "IPAMConfig": None}}},
}


def test_build_create_body_keeps_user_config_and_takes_new_image_defaults():
    body = build_create_body(CONTAINER, OLD_IMAGE, NEW_IMAGE, "searxng/searxng:latest")
    env = dict(e.split("=", 1) for e in body["Env"])
    assert env["__SEARXNG_VERSION"] == "2026.10.4-bbb"     # new image default wins
    assert env["TZ"] == "Europe/Berlin"                     # user env kept
    assert body["Labels"] == {"com.docker.compose.service": "searxng"}
    assert "Hostname" not in body and "Entrypoint" not in body and "Volumes" not in body
    assert body["HostConfig"]["Binds"] == ["/srv/searxng:/etc/searxng"]
    assert body["NetworkingConfig"]["EndpointsConfig"]["search_default"] == {"Aliases": ["searxng"]}


def test_host_network_has_no_endpoint_config():
    c = {**CONTAINER, "HostConfig": {"NetworkMode": "host"}, "NetworkSettings": {"Networks": {"host": {}}}}
    body = build_create_body(c, OLD_IMAGE, NEW_IMAGE, "searxng/searxng:latest")
    assert "NetworkingConfig" not in body


def test_split_ref():
    assert split_ref("searxng/searxng") == ("searxng/searxng", "latest")
    assert split_ref("docker.io/searxng/searxng:2026.10.4-x") == ("docker.io/searxng/searxng", "2026.10.4-x")
    assert split_ref("localhost:5000/sx:edge") == ("localhost:5000/sx", "edge")
