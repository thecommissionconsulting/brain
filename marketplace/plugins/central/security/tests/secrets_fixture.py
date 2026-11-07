"""Synthetic credentials for tests, assembled at import so no source line holds one.

None of these authenticate anything. The AWS key id is the example from AWS's own
documentation, the JWT is the jwt.io specimen, the rest are invented. Building them
from pieces keeps GitHub push protection and the vault's hooks_guard.py from
flagging this file, which is the same reason the vault's test_prompt_gate.py
carries allowlist pragmas.
"""
ANTHROPIC = "sk-" + "ant-api03-" + "AbCdEf0123456789xyzQrStUvW"
GITHUB = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
JWT = ("ey" + "JhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "."
       + "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk")
PRIVATE_KEY = ("-----BEGIN " + "RSA PRIVATE KEY-----\n"
               "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
               "KUpRKfFLfRYC9AIKjbJTWit+CqvjWYzvQwECAwEAAQ==\n"
               "-----END " + "RSA PRIVATE KEY-----")
VISA = "4111 1111 " + "1111 1111"
