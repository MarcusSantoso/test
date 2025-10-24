from datetime import datetime, timezone
from typing import Dict, Any, Optional

from authlib.jose import JsonWebKey, jwt

# NOTE: For the exercise we generate an in-memory RSA keypair. In real
# deployments load a persistent private key from secure storage.
_jwk = JsonWebKey.generate_key(kty="RSA", crv_or_size=2048, is_private=True)
_private_jwk = _jwk.as_dict(is_private=True)
_public_jwk = _jwk.as_dict()

ALGORITHM = "RS256"


class JWTError(Exception):
    pass


def issue_jwt(sub: int, expiry_dt: datetime, extra: Optional[Dict[str, Any]] = None, iat: Optional[int] = None) -> str:
    """Issue an RS256 JWT.

    If `iat` is provided (an int epoch seconds) it will be used as the
    issued-at claim. Otherwise the current UTC time is used.
    """
    if iat is None:
        now = datetime.now(tz=timezone.utc)
        # use millisecond precision to avoid collisions when tokens are
        # minted in rapid succession during tests
        iat_val = int(now.timestamp() * 1000)
    else:
        iat_val = int(iat)
    payload = {
        "sub": int(sub),
        "exp": int(expiry_dt.replace(tzinfo=timezone.utc).timestamp()),
        # store iat as integer milliseconds
        "iat": int(iat_val),
    }
    if extra:
        payload.update(extra)

    header = {"alg": ALGORITHM, "typ": "JWT"}
    token = jwt.encode(header, payload, _private_jwk)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def verify_jwt(token: str) -> Dict[str, Any]:
    try:
        claims = jwt.decode(token, _public_jwk)
        # Validate expiration
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        exp = int(claims.get("exp", 0))
        if exp <= now_ts:
            raise JWTError("Token has expired")
        return dict(claims)
    except Exception as exc:
        raise JWTError(str(exc)) from exc
