#!/usr/bin/python3

"""AST Nodes and SExpr reader/writer for the Cwerg frontend


"""

import sys
import re
import dataclasses
import logging
import enum
from typing import List, Dict, Set, Optional, Union, Any

from FrontEnd import cwast

logger = logging.getLogger(__name__)
############################################################
# S-Expression Serialization (Introspection driven)
############################################################


# Note: we rely on the matching being done greedily
_TOKEN_CHAR = r"['][^\\']*(?:[\\].[^\\']*)*(?:[']|$)"
_TOKEN_STR = r'["][^\\"]*(?:[\\].[^\\"]*)*(?:["]|$)'
_TOKEN_NAMENUM = r'[^\[\]\(\)\' \r\n\t]+'
_TOKEN_OP = r'[\[\]\(\)]'
_TOKENS_ALL = re.compile("|".join(["(?:" + x + ")" for x in [
    _TOKEN_STR, _TOKEN_CHAR, _TOKEN_OP, _TOKEN_NAMENUM]]))

_TOKEN_ID = re.compile(r'[_A-Za-z$][_A-Za-z$0-9]*(::[_A-Za-z$][_A-Za-z$0-9])*')
_TOKEN_NUM = re.compile(r'[.0-9][_.a-z0-9]*')


class ReadTokens:
    def __init__(self, fp):
        self._fp = fp
        self.line_no = 0
        self._tokens = []

    def __iter__(self):
        return self

    def srcloc(self):
        # TODO: should also reflect the file once we support multiple input files
        return self.line_no

    def __next__(self):
        while not self._tokens:
            self._tokens = re.findall(_TOKENS_ALL, next(self._fp))
            self.line_no += 1
        return self._tokens.pop(0)


_SCALAR_TYPES = [
    #
    cwast.BASE_TYPE_KIND.SINT,
    cwast.BASE_TYPE_KIND.S8,
    cwast.BASE_TYPE_KIND.S16,
    cwast.BASE_TYPE_KIND.S32,
    cwast.BASE_TYPE_KIND.S64,
    #
    cwast.BASE_TYPE_KIND.UINT,
    cwast.BASE_TYPE_KIND.U8,
    cwast.BASE_TYPE_KIND.U16,
    cwast.BASE_TYPE_KIND.U32,
    cwast.BASE_TYPE_KIND.U64,
    #
    cwast.BASE_TYPE_KIND.R32,
    cwast.BASE_TYPE_KIND.R64,
]


def _MakeTypeBaseLambda(kind: cwast.BASE_TYPE_KIND):
    return lambda srcloc: cwast.TypeBase(kind, x_srcloc=srcloc)


# maps "atoms" to the nodes they will be expanded to
_SHORT_HAND_NODES = {
    "auto": lambda srcloc: cwast. TypeAuto(x_srcloc=srcloc),
    #
    "noret": _MakeTypeBaseLambda(cwast.BASE_TYPE_KIND.NORET),
    "bool": _MakeTypeBaseLambda(cwast.BASE_TYPE_KIND.BOOL),
    "void": _MakeTypeBaseLambda(cwast.BASE_TYPE_KIND.VOID),
    #
    "void_val": lambda srcloc: cwast.ValVoid(x_srcloc=srcloc),
    "undef": lambda srcloc: cwast.ValUndef(x_srcloc=srcloc),
    "true": lambda srcloc: cwast.ValTrue(x_srcloc=srcloc),
    "false": lambda srcloc: cwast.ValFalse(x_srcloc=srcloc),
}


for t in _SCALAR_TYPES:
    name = t.name.lower()
    _SHORT_HAND_NODES[name] = _MakeTypeBaseLambda(t)


def ExpandShortHand(t, srcloc) -> Any:
    """Expands atoms, ids, and numbers to proper nodes"""
    x = _SHORT_HAND_NODES.get(t)
    if x is not None:
        return x(srcloc)

    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        # TODO: r"
        return cwast.ValString(False, t, x_srcloc=srcloc)
    elif _TOKEN_ID.match(t):
        if t[0] == "$":
            return cwast.MacroId(t, x_srcloc=srcloc)
        parts = t.rsplit("::", 1)
        return cwast.Id(parts[-1], "" if len(parts) ==
                        1 else parts[0], x_srcloc=srcloc)
    elif _TOKEN_NUM.match(t):
        return cwast.ValNum(t, x_srcloc=srcloc)
    elif len(t) >= 3 and t[0] == "'" and t[-1] == "'":
        return cwast.ValNum(t, x_srcloc=srcloc)
    else:
        return None


def ReadNodeList(stream: ReadTokens, parent_cls):
    out = []
    while True:
        token = next(stream)
        if token == "]":
            break
        if token == "(":
            out.append(ReadSExpr(stream, parent_cls))
        else:
            out.append(ExpandShortHand(token, stream.srcloc()))
    return out


def ReadStrList(stream) -> List[str]:
    out = []
    while True:
        token = next(stream)
        if token == "]":
            break
        else:
            out.append(token)
    return out


def ReadPiece(field, token, stream: ReadTokens, parent_cls) -> Any:
    """Read a single component of an SExpr including lists."""
    nfd = cwast. ALL_FIELDS_MAP[field]
    if nfd.kind is cwast.NFK.FLAG:
        return bool(token)
    elif nfd.kind is cwast.NFK.STR:
        return token
    elif nfd.kind is cwast.NFK.INT:
        return token
    elif nfd.kind is cwast.NFK.KIND:
        assert nfd.extra is not None, f"{field} {token}"
        return nfd.extra[token]
    elif nfd.kind is cwast.NFK.NODE:
        if token == "(":
            return ReadSExpr(stream, parent_cls)
        out = ExpandShortHand(token, stream.srcloc())
        assert out is not None, f"Cannot expand {token} for {field}"
        return out
    elif nfd.kind is cwast.NFK.STR_LIST:
        assert token == "[", f"expected list start for: {field} {token}"
        return ReadStrList(stream)
    elif nfd.kind is cwast.NFK.LIST:
        assert token == "[", f"expected list start for: {field} {token}"
        return ReadNodeList(stream, parent_cls)
    else:
        assert None


def ReadMacroInvocation(tag, stream: ReadTokens):
    parent_cls = cwast.MacroInvoke
    srcloc = stream.srcloc()
    logger.info("Readdng MACRO INVOCATION %s at %s", tag, srcloc)
    args = []
    while True:
        token = next(stream)
        if token == ")":
            return cwast.MacroInvoke(tag, args, x_srcloc=srcloc)
        elif token == "(":
            args.append(ReadSExpr(stream, parent_cls))
        elif token == "[":
            args.append(cwast.EphemeralList(ReadNodeList(
                stream, parent_cls), x_srcloc=srcloc))
        else:
            out = ExpandShortHand(token, stream.srcloc())
            assert out is not None, f"while processing {tag} unexpected macro arg: {token}"
            args.append(out)
    return args


def ReadRestAndMakeNode(cls, pieces: List[Any], fields: List[str], stream: ReadTokens):
    """Read the remaining componts of an SExpr (after the tag).

    Can handle optional bools at the beginning and an optional 'tail'
    """
    srcloc = stream.srcloc()
    logger.info("Readding TAG %s at %s", cls.__name__, srcloc)
    token = next(stream)
    for field in fields:
        nfd = cwast.ALL_FIELDS_MAP[field]
        if token == ")":
            # we have reached the end before all the fields were processed
            # fill in default values
            assert field in cwast.OPTIONAL_FIELDS, f"in {cls.__name__} unknown optional (or missing) field: {field}"
            pieces.append(cwast.OPTIONAL_FIELDS[field](srcloc))
        elif nfd.kind is cwast.NFK.FLAG:
            if token == field:
                pieces.append(True)
                token = next(stream)
            else:
                pieces.append(False)
        else:
            pieces.append(ReadPiece(field, token, stream, cls))
            token = next(stream)
    if token != ")":
        cwast.CompilerError(stream.srcloc(
        ), f"while parsing {cls.__name__} expected node-end but got {token}")
    return cls(*pieces, x_srcloc=srcloc)


def ReadSExpr(stream: ReadTokens, parent_cls) -> Any:
    """The leading '(' has already been consumed"""
    tag = next(stream)
    if tag in cwast.UNARY_EXPR_SHORTCUT:
        return ReadRestAndMakeNode(cwast.Expr1, [cwast.UNARY_EXPR_SHORTCUT[tag]],
                                   ["expr"], stream)
    elif tag in cwast.BINARY_EXPR_SHORTCUT:
        return ReadRestAndMakeNode(cwast.Expr2, [cwast.BINARY_EXPR_SHORTCUT[tag]],
                                   ["expr1", "expr2"], stream)
    elif tag in cwast.ASSIGNMENT_SHORTCUT:
        return ReadRestAndMakeNode(cwast.StmtCompoundAssignment, [cwast.ASSIGNMENT_SHORTCUT[tag]],
                                   ["lhs", "expr"], stream)
    else:
        cls = cwast.NODES_ALIASES.get(tag)
        if not cls:
            # unknown node name - assume it is a macro
            return ReadMacroInvocation(tag, stream)
        assert cls is not None, f"[{stream.line_no}] Non node: {tag}"

        # This helps catching missing closing braces early
        if cwast.NF.TOP_LEVEL in cls.FLAGS:
            if parent_cls is not cwast.DefMod:
                cwast.CompilerError(stream.srcloc(
                ), f"toplevel node {cls.__name__} not allowed in {parent_cls.__name__}")

        fields = [f for f, _ in cls.__annotations__.items()
                  if not f.startswith("x_")]
        return ReadRestAndMakeNode(cls, [], fields, stream)


def ReadModsFromStream(fp) -> List[cwast.DefMod]:
    asts = []
    stream = ReadTokens(fp)
    try:
        failure = False
        while True:
            t = next(stream)
            failure = True
            if t != "(":
                cwast.CompilerError(stream.srcloc(), f"expect start of new node, got '{t}']") 
            sexpr = ReadSExpr(stream, None)
            assert isinstance(sexpr, cwast.DefMod)
            cwast.CheckAST(sexpr, None, cwast.CheckASTContext())
            asts.append(sexpr)
            failure = False
    except StopIteration:
        assert not failure, f"truncated file"
    return asts





if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.WARN)
    logger.setLevel(logging.INFO)
    ReadModsFromStream(sys.stdin)