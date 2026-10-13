from __future__ import annotations

import os
import ssl
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any


SYSTEM_CA_CANDIDATES = (
    "/etc/ssl/cert.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/certs/ca-certificates.crt",
)


@lru_cache(maxsize=1)
def create_ssl_context() -> ssl.SSLContext:
    cafile = os.getenv("SSL_CERT_FILE", "").strip() or None
    capath = os.getenv("SSL_CERT_DIR", "").strip() or None
    context = ssl.create_default_context(cafile=cafile, capath=capath)
    if cafile or capath:
        return context

    default_paths = ssl.get_default_verify_paths()
    default_cafile = default_paths.cafile
    if default_cafile and Path(default_cafile).is_file():
        return context

    for candidate in SYSTEM_CA_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            context.load_verify_locations(cafile=str(path))
            return context
    return context


def open_url(request: urllib.request.Request | str, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout, context=create_ssl_context())
