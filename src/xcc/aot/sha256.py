uint32 = int


def _right_rotate(value: uint32, count: int) -> uint32:
    return ((value >> count) | (value << (32 - count))) & 0xFFFFFFFF


def _round_constants() -> tuple[uint32, ...]:
    return (
        0x428A2F98,
        0x71374491,
        0xB5C0FBCF,
        0xE9B5DBA5,
        0x3956C25B,
        0x59F111F1,
        0x923F82A4,
        0xAB1C5ED5,
        0xD807AA98,
        0x12835B01,
        0x243185BE,
        0x550C7DC3,
        0x72BE5D74,
        0x80DEB1FE,
        0x9BDC06A7,
        0xC19BF174,
        0xE49B69C1,
        0xEFBE4786,
        0x0FC19DC6,
        0x240CA1CC,
        0x2DE92C6F,
        0x4A7484AA,
        0x5CB0A9DC,
        0x76F988DA,
        0x983E5152,
        0xA831C66D,
        0xB00327C8,
        0xBF597FC7,
        0xC6E00BF3,
        0xD5A79147,
        0x06CA6351,
        0x14292967,
        0x27B70A85,
        0x2E1B2138,
        0x4D2C6DFC,
        0x53380D13,
        0x650A7354,
        0x766A0ABB,
        0x81C2C92E,
        0x92722C85,
        0xA2BFE8A1,
        0xA81A664B,
        0xC24B8B70,
        0xC76C51A3,
        0xD192E819,
        0xD6990624,
        0xF40E3585,
        0x106AA070,
        0x19A4C116,
        0x1E376C08,
        0x2748774C,
        0x34B0BCB5,
        0x391C0CB3,
        0x4ED8AA4A,
        0x5B9CCA4F,
        0x682E6FF3,
        0x748F82EE,
        0x78A5636F,
        0x84C87814,
        0x8CC70208,
        0x90BEFFFA,
        0xA4506CEB,
        0xBEF9A3F7,
        0xC67178F2,
    )


def _word(data: bytes, offset: int) -> uint32:
    return (
        (data[offset] << 24) | (data[offset + 1] << 16) | (data[offset + 2] << 8) | data[offset + 3]
    )


def _hex32(value: uint32) -> str:
    digits = "0123456789abcdef"
    result = ""
    shift = 28
    while shift >= 0:
        result += digits[(value >> shift) & 0xF]
        shift -= 4
    return result


def sha256_hex(data: bytes) -> str:
    bit_length = len(data) * 8
    message = data + b"\x80"
    message += b"\x00" * ((56 - (len(message) % 64)) % 64)
    message += bit_length.to_bytes(8, "big")

    h0: uint32 = 0x6A09E667
    h1: uint32 = 0xBB67AE85
    h2: uint32 = 0x3C6EF372
    h3: uint32 = 0xA54FF53A
    h4: uint32 = 0x510E527F
    h5: uint32 = 0x9B05688C
    h6: uint32 = 0x1F83D9AB
    h7: uint32 = 0x5BE0CD19
    constants = _round_constants()

    offset = 0
    while offset < len(message):
        schedule: list[uint32] = []
        index = 0
        while index < 16:
            schedule.append(_word(message, offset + index * 4))
            index += 1
        while index < 64:
            before_15 = schedule[index - 15]
            before_2 = schedule[index - 2]
            sigma0 = _right_rotate(before_15, 7) ^ _right_rotate(before_15, 18) ^ (before_15 >> 3)
            sigma1 = _right_rotate(before_2, 17) ^ _right_rotate(before_2, 19) ^ (before_2 >> 10)
            schedule.append(
                (schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1) & 0xFFFFFFFF
            )
            index += 1

        a = h0
        b = h1
        c = h2
        d = h3
        e = h4
        f = h5
        g = h6
        h = h7
        index = 0
        while index < 64:
            sum1 = _right_rotate(e, 6) ^ _right_rotate(e, 11) ^ _right_rotate(e, 25)
            choice = (e & f) ^ ((~e) & g)
            temp1 = (h + sum1 + choice + constants[index] + schedule[index]) & 0xFFFFFFFF
            sum0 = _right_rotate(a, 2) ^ _right_rotate(a, 13) ^ _right_rotate(a, 22)
            majority = (a & b) ^ (a & c) ^ (b & c)
            temp2 = (sum0 + majority) & 0xFFFFFFFF
            h = g
            g = f
            f = e
            e = (d + temp1) & 0xFFFFFFFF
            d = c
            c = b
            b = a
            a = (temp1 + temp2) & 0xFFFFFFFF
            index += 1

        h0 = (h0 + a) & 0xFFFFFFFF
        h1 = (h1 + b) & 0xFFFFFFFF
        h2 = (h2 + c) & 0xFFFFFFFF
        h3 = (h3 + d) & 0xFFFFFFFF
        h4 = (h4 + e) & 0xFFFFFFFF
        h5 = (h5 + f) & 0xFFFFFFFF
        h6 = (h6 + g) & 0xFFFFFFFF
        h7 = (h7 + h) & 0xFFFFFFFF
        offset += 64

    return (
        _hex32(h0)
        + _hex32(h1)
        + _hex32(h2)
        + _hex32(h3)
        + _hex32(h4)
        + _hex32(h5)
        + _hex32(h6)
        + _hex32(h7)
    )
