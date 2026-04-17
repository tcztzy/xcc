import ast
import re
from dataclasses import dataclass

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_PP_INT_RE = re.compile(
    r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?$"
)
_EXPR_TOKEN_RE = re.compile(
    r"0[xX][0-9A-Fa-f]+(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?"
    r"|[0-9]+(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?"
    r"|(?:u8|[uUL])?'(?:[^'\\\n]|\\.)+'"
    r"|[A-Za-z_]\w*"
    r"|\|\||&&|==|!=|<=|>=|<<|>>|[()!~+\-*/%<>&^|?:]"
)

_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_UINT64_MASK = (1 << 64) - 1


def _rewrite_ternary(tokens: list[str]) -> list[str]:
    """Rewrite C ternary ``A ? B : C`` sequences to Python ``( B if A else C )``."""
    processed: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "(":
            depth = 1
            j = i + 1
            while j < len(tokens) and depth > 0:
                if tokens[j] == "(":
                    depth += 1
                elif tokens[j] == ")":
                    depth -= 1
                j += 1
            inner = _rewrite_ternary(tokens[i + 1 : j - 1])
            processed.append("(")
            processed.extend(inner)
            processed.append(")")
            i = j
        else:
            processed.append(tokens[i])
            i += 1
    tokens = processed
    question = -1
    depth = 0
    for i in range(len(tokens)):
        if tokens[i] == "(":
            depth += 1
        elif tokens[i] == ")":
            depth -= 1
        elif tokens[i] == "?" and depth == 0:
            question = i
            break
    if question == -1:
        return tokens
    colon = -1
    ternary_depth = 1
    paren_depth = 0
    for i in range(question + 1, len(tokens)):
        if tokens[i] == "(":
            paren_depth += 1
        elif tokens[i] == ")":
            paren_depth -= 1
        elif paren_depth == 0:
            if tokens[i] == "?":
                ternary_depth += 1
            elif tokens[i] == ":":
                ternary_depth -= 1
                if ternary_depth == 0:
                    colon = i
                    break
    if colon == -1:
        raise ValueError("Invalid token")
    condition = _rewrite_ternary(tokens[:question])
    true_branch = _rewrite_ternary(tokens[question + 1 : colon])
    false_branch = _rewrite_ternary(tokens[colon + 1 :])
    return ["("] + true_branch + ["if"] + condition + ["else"] + false_branch + [")"]


def _translate_expr_to_python(expr: str) -> str:
    tokens = _tokenize_expr(expr)
    tokens = _collapse_function_invocations(tokens)
    mapped: list[str] = []
    for token in tokens:
        value = _parse_pp_integer_literal(token)
        if value is not None:
            if value > _UINT64_MASK:
                raise ValueError("Integer literal overflow")
            if _is_unsigned_pp_integer(token):
                mapped.append(f"u64({value})")
            else:
                mapped.append(str(value))
            continue
        char_value = _parse_pp_char_literal(token)
        if char_value is not None:
            mapped.append(str(char_value))
            continue
        if _IDENT_RE.fullmatch(token):
            mapped.append("0")
            continue
        if token == "&&":
            mapped.append("and")
            continue
        if token == "||":
            mapped.append("or")
            continue
        if token == "!":
            mapped.append("not")
            continue
        if token == "/":
            mapped.append("//")
            continue
        mapped.append(token)
    mapped = _rewrite_ternary(mapped)
    return " ".join(mapped)


def _collapse_function_invocations(tokens: list[str]) -> list[str]:
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _IDENT_RE.fullmatch(token) and index + 1 < len(tokens) and tokens[index + 1] == "(":
            depth = 0
            index += 1
            while index < len(tokens):
                next_token = tokens[index]
                if next_token == "(":
                    depth += 1
                elif next_token == ")":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            if depth != 0:
                raise ValueError("Invalid token")
            collapsed.append("0")
            continue
        collapsed.append(token)
        index += 1
    return collapsed


def _parse_pp_integer_literal(token: str) -> int | None:
    if _PP_INT_RE.fullmatch(token) is None:
        return None
    index = len(token)
    while index > 0 and token[index - 1] in "uUlL":
        index -= 1
    digits = token[:index]
    if digits.startswith(("0x", "0X")):
        return int(digits, 16)
    if digits.startswith("0") and len(digits) > 1:
        if any(ch not in "01234567" for ch in digits):
            return None
        return int(digits, 8)
    return int(digits, 10)


def _is_unsigned_pp_integer(token: str) -> bool:
    value = _parse_pp_integer_literal(token)
    if value is None:
        return False
    return any(ch in "uU" for ch in token) or value > _INT64_MAX


def _parse_pp_char_literal(token: str) -> int | None:
    literal = token
    for prefix in ("u8", "u", "U", "L"):
        if literal.startswith(prefix):
            literal = literal[len(prefix) :]
            break
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(value, str) or not value:
        return None
    result = 0
    for char in value:
        result = (result << 8) | (ord(char) & 0xFF)
    return result


def _strip_condition_comments(expr: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", " ", expr)
    if "//" in without_block:
        return without_block.split("//", 1)[0]
    return without_block


def _tokenize_expr(expr: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(expr):
        if expr[index].isspace():
            index += 1
            continue
        match = _EXPR_TOKEN_RE.match(expr, index)
        if match is None:
            raise ValueError("Invalid token")
        tokens.append(match.group(0))
        index = match.end()
    return tokens


def _safe_eval_int_expr(expr: str) -> int:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError("Invalid expression") from error
    return _eval_node(node)


class _PPExprOverflow(ValueError):
    pass


@dataclass(frozen=True)
class _PPValue:
    value: int
    is_unsigned: bool = False

    def as_unsigned(self) -> int:
        return self.value & _UINT64_MASK

    def normalize(self) -> "_PPValue":
        if self.is_unsigned:
            return _PPValue(self.value & _UINT64_MASK, True)
        if self.value < _INT64_MIN or self.value > _INT64_MAX:
            raise _PPExprOverflow("integer overflow in preprocessor expression")
        return self


def _safe_eval_pp_expr(expr: str) -> int:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError("Invalid expression") from error
    try:
        return _eval_pp_node(node).value
    except ZeroDivisionError as error:
        raise ValueError("Invalid expression") from error


def _eval_pp_node(node: ast.AST) -> _PPValue:
    if isinstance(node, ast.Expression):
        return _eval_pp_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return _PPValue(int(node.value))
        if isinstance(node.value, int):
            if node.value > _UINT64_MASK or node.value < _INT64_MIN:
                raise _PPExprOverflow("integer overflow in preprocessor expression")
            if node.value > _INT64_MAX:
                return _PPValue(node.value, True).normalize()
            return _PPValue(node.value)
        raise ValueError(f"Unsupported preprocessor literal type: {type(node.value).__name__}")
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "u64"
            and len(node.args) == 1
            and not node.keywords
        ):
            value = _eval_pp_node(node.args[0])
            return _PPValue(value.as_unsigned(), True)
        raise ValueError("Unsupported preprocessor call expression")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_pp_node(node.operand)
        if isinstance(node.op, ast.Not):
            return _PPValue(0 if operand.value else 1)
        if isinstance(node.op, ast.UAdd):
            return operand.normalize()
        if isinstance(node.op, ast.USub):
            value = -operand.value
            result = _PPValue(value, operand.is_unsigned)
            return result.normalize()
        if isinstance(node.op, ast.Invert):
            value = ~operand.value
            result = _PPValue(value, operand.is_unsigned)
            return result.normalize()
        raise ValueError(f"Unsupported preprocessor unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if _eval_pp_node(value).value == 0:
                    return _PPValue(0)
            return _PPValue(1)
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_pp_node(value).value != 0:
                    return _PPValue(1)
            return _PPValue(0)
        raise ValueError(f"Unsupported preprocessor boolean operator: {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        left = _eval_pp_node(node.left)
        right = _eval_pp_node(node.right)
        is_unsigned = left.is_unsigned or right.is_unsigned
        left_value = left.as_unsigned() if is_unsigned else left.value
        right_value = right.as_unsigned() if is_unsigned else right.value
        if isinstance(node.op, ast.Add):
            value = left_value + right_value
        elif isinstance(node.op, ast.Sub):
            value = left_value - right_value
        elif isinstance(node.op, ast.Mult):
            value = left_value * right_value
        elif isinstance(node.op, ast.FloorDiv):
            value = left_value // right_value
        elif isinstance(node.op, ast.Mod):
            value = left_value % right_value
        elif isinstance(node.op, ast.LShift):
            value = left_value << right_value
        elif isinstance(node.op, ast.RShift):
            value = left_value >> right_value
        elif isinstance(node.op, ast.BitOr):
            value = left_value | right_value
        elif isinstance(node.op, ast.BitAnd):
            value = left_value & right_value
        elif isinstance(node.op, ast.BitXor):
            value = left_value ^ right_value
        else:
            raise ValueError(f"Unsupported preprocessor binary operator: {type(node.op).__name__}")
        result = _PPValue(value, is_unsigned)
        return result.normalize()
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ValueError(
                "Unsupported preprocessor comparison shape: "
                f"expected 1 operator, got {len(node.ops)}"
            )
        if len(node.comparators) != 1:
            raise ValueError(
                "Unsupported preprocessor comparison shape: "
                f"expected 1 comparator, got {len(node.comparators)}"
            )
        left = _eval_pp_node(node.left)
        right = _eval_pp_node(node.comparators[0])
        is_unsigned = left.is_unsigned or right.is_unsigned
        left_value = left.as_unsigned() if is_unsigned else left.value
        right_value = right.as_unsigned() if is_unsigned else right.value
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return _PPValue(int(left_value == right_value))
        if isinstance(op, ast.NotEq):
            return _PPValue(int(left_value != right_value))
        if isinstance(op, ast.Lt):
            return _PPValue(int(left_value < right_value))
        if isinstance(op, ast.LtE):
            return _PPValue(int(left_value <= right_value))
        if isinstance(op, ast.Gt):
            return _PPValue(int(left_value > right_value))
        if isinstance(op, ast.GtE):
            return _PPValue(int(left_value >= right_value))
        raise ValueError(f"Unsupported preprocessor comparison operator: {type(op).__name__}")
    if isinstance(node, ast.IfExp):
        condition = _eval_pp_node(node.test)
        if condition.value:
            result = _eval_pp_node(node.body)
            try:
                other = _eval_pp_node(node.orelse)
                is_unsigned = result.is_unsigned or other.is_unsigned
            except (ValueError, ZeroDivisionError):
                is_unsigned = result.is_unsigned
        else:
            result = _eval_pp_node(node.orelse)
            try:
                other = _eval_pp_node(node.body)
                is_unsigned = result.is_unsigned or other.is_unsigned
            except (ValueError, ZeroDivisionError):
                is_unsigned = result.is_unsigned
        if is_unsigned:
            return _PPValue(result.as_unsigned(), True)
        return result
    raise ValueError(f"Unsupported preprocessor expression node: {type(node).__name__}")


def _eval_node(node: ast.AST) -> int:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return int(node.value)
        if isinstance(node.value, int):
            return node.value
        raise ValueError(
            f"Unsupported integer-expression literal type: {type(node.value).__name__}"
        )
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        if isinstance(node.op, ast.Not):
            return 0 if value else 1
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        raise ValueError(f"Unsupported integer-expression unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if _eval_node(value) == 0:
                    return 0
            return 1
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_node(value) != 0:
                    return 1
            return 0
        raise ValueError(
            f"Unsupported integer-expression boolean operator: {type(node.op).__name__}"
        )
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.LShift):
            return left << right
        if isinstance(node.op, ast.RShift):
            return left >> right
        if isinstance(node.op, ast.BitOr):
            return left | right
        if isinstance(node.op, ast.BitAnd):
            return left & right
        if isinstance(node.op, ast.BitXor):
            return left ^ right
        raise ValueError(
            f"Unsupported integer-expression binary operator: {type(node.op).__name__}"
        )
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ValueError(
                "Unsupported integer-expression comparison shape: "
                f"expected 1 operator, got {len(node.ops)}"
            )
        if len(node.comparators) != 1:
            raise ValueError(
                "Unsupported integer-expression comparison shape: "
                f"expected 1 comparator, got {len(node.comparators)}"
            )
        left = _eval_node(node.left)
        right = _eval_node(node.comparators[0])
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return int(left == right)
        if isinstance(op, ast.NotEq):
            return int(left != right)
        if isinstance(op, ast.Lt):
            return int(left < right)
        if isinstance(op, ast.LtE):
            return int(left <= right)
        if isinstance(op, ast.Gt):
            return int(left > right)
        if isinstance(op, ast.GtE):
            return int(left >= right)
        raise ValueError(f"Unsupported integer-expression comparison operator: {type(op).__name__}")
    raise ValueError(f"Unsupported integer-expression node: {type(node).__name__}")
