#!/usr/bin/python3

"""Type annotator for Cwerg AST

"""

import sys
import logging

from FrontEnd import cwast
from FrontEnd import symbolize
from FrontEnd import types

from typing import List, Dict, Set, Optional, Union, Any

logger = logging.getLogger(__name__)


def is_proper_lhs(node):
    # TODO: this needs to be rethought and cleaned up
    return (types.is_mutable_def(node) or
            isinstance(node, cwast.ExprDeref) and types.is_mutable(node.expr.x_type) or
            isinstance(node, cwast.ExprField) and is_proper_lhs(node.container) or
            isinstance(node, cwast.ExprIndex) and types.is_mutable_def(node.container) or
            isinstance(node, cwast.ExprIndex) and types.is_mutable(node.container.x_type))


def ComputeStringSize(raw: bool, string: str) -> int:
    assert string[0] == '"'
    assert string[-1] == '"'
    string = string[1:-1]
    n = len(string)
    if raw:
        return n
    esc = False
    for c in string:
        if esc:
            esc = False
            if c == "x":
                n -= 3
            else:
                n -= 1
        elif c == "\\":
            esc = True
    return 8


def ParseNum(num: str, kind: cwast.BASE_TYPE_KIND) -> int:
    # TODO use kind argument
    num = num.replace("_", "")
    if num[-3:] in ("u16", "u32", "u64", "s16", "s32", "s64"):
        return int(num[: -3])
    elif num[-2:] in ("u8", "s8"):
        return int(num[: -2])
    elif num[-4:] in ("uint", "sint"):
        return int(num[: -4])
    elif num[-3:] in ("r32", "r64"):
        return float(num[: -3])
    if num[0] == "'":
        assert num[-1] == "'"
        if num[1] == "\\":
            if num[2] == "n":
                return 10
            assert False, f"unsupported escape sequence: [{num}]"

        else:
            return ord(num[1])
    else:
        return int(num)


def ParseArrayIndex(pos: str) -> int:
    return int(pos)


class _PolyMap:

    def __init__(self, type_corpus: types.TypeCorpus):
        self._map = {}
        self._type_corpus = type_corpus

    def Register(self, fun: cwast.DefFun):
        cstr = fun.x_type
        first_param_type = self._type_corpus.canon_name(
            cstr.params[0].type)
        logger.info("Register polymorphic fun %s: %s",
                    fun.name, first_param_type)
        self._map[(fun.name, first_param_type)] = fun

    def Resolve(self, fun_name: str, first_param_type) -> cwast.DefFun:
        type_name = self._type_corpus.canon_name(first_param_type)
        logger.info("Resolving polymorphic fun %s: %s",
                    fun_name, type_name)
        out = self._map.get((fun_name, type_name))
        if out:
            return out
        if isinstance(first_param_type, cwast.TypeArray):
            slice_type = self._type_corpus. insert_slice_type(
                False, first_param_type.type)
        type_name = self._type_corpus.canon_name(slice_type)
        out = self._map.get((fun_name, type_name))
        if out:
            return out
        assert False, f"cannot resolve polymorphic {fun_name}"


class _TypeContext:
    def __init__(self, mod_name, poly_map: _PolyMap):
        self.mod_name: str = mod_name
        self.enclosing_fun: Optional[cwast.DefFun] = None
        self._enclosing_rec_type: List[types.CanonType] = []
        self._target_type: List[types.CanonType] = [types.NO_TYPE]
        self._poly_map: _PolyMap = poly_map

    def push_target(self, cstr: types.CanonType):
        """use to suport limited type inference

        contains the type the current expression/type is expected to
        have or types.types.NO_TYPE
        """

        self._target_type.append(cstr)

    def pop_target(self):
        self._target_type.pop(-1)

    def get_target_type(self):
        return self._target_type[-1]


def is_compatible_for_as(self, src: types.CanonType, dst: types.CanonType) -> bool:
    # TODO: deal with distinct types

    if types.is_int(src):
        return types.is_int(dst) or types.is_real(dst)


def _ComputeArrayLength(node) -> int:
    if isinstance(node, cwast.ValNum):
        return ParseNum(node.number, cwast.BASE_TYPE_KIND.INVALID)
    elif isinstance(node, cwast.Id):
        node = node.x_symbol
        return _ComputeArrayLength(node)
    elif isinstance(node, (cwast.DefVar,cwast.DefGlobal)) and not node.mut:
        return _ComputeArrayLength(node.initial_or_undef)
    else:
        assert False, f"unexpected dim node: {node}"


def _AnnotateType(corpus, node, cstr: types.CanonType):
    logger.info(f"TYPE of {node}: {corpus.canon_name(cstr)}")
    assert cwast.NF.TYPE_CORPUS in cstr.__class__.FLAGS, f"bad type corpus node {repr(cstr)}"
    assert cwast.NF.TYPE_ANNOTATED in node.__class__.FLAGS, f"node not meant for type annotation: {node}"
    assert cstr, f"No valid type for {node}"
    assert node.x_type is None, f"duplicate annotation for {node}"
    node.x_type = cstr
    return cstr


def _AnnotateField(node, field_node: cwast.RecField):
    assert isinstance(
        node, (cwast.ExprField, cwast.FieldVal, cwast.ExprOffsetof))
    assert node.x_field is None
    node.x_field = field_node


def _TypifyNodeRecursively(node, corpus: types.TypeCorpus, ctx: _TypeContext) -> types.CanonType:
    target_type = ctx.get_target_type()
    extra = "" if target_type == types.NO_TYPE else f"[{target_type}]"
    logger.debug(f"TYPIFYING{extra} {node}")
    cstr = None
    if cwast.NF.TYPE_ANNOTATED in node.FLAGS:
        cstr = node.x_type
    if cstr is not None:
        # has been typified already
        return cstr
    if isinstance(node, cwast.Comment):
        return types.NO_TYPE
    elif isinstance(node, cwast.Id):
        # this case is why we need the sym_tab
        def_node = node.x_symbol
        # assert isinstance(def_node, cwast.DefType), f"unexpected node {def_node}"
        cstr = _TypifyNodeRecursively(def_node, corpus, ctx)
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.TypeBase):
        return _AnnotateType(corpus, node, corpus.insert_base_type(node.base_type_kind))
    elif isinstance(node, cwast.TypePtr):
        t = _TypifyNodeRecursively(node.type, corpus, ctx)
        return _AnnotateType(corpus, node, corpus.insert_ptr_type(node.mut, t))
    elif isinstance(node, cwast.TypeSlice):
        t = _TypifyNodeRecursively(node.type, corpus, ctx)
        return _AnnotateType(corpus, node, corpus.insert_slice_type(node.mut, t))
    elif isinstance(node, cwast.FunParam):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, (cwast.TypeFun, cwast.DefFun)):
        params = [_TypifyNodeRecursively(p, corpus, ctx)
                  for p in node.params if not isinstance(p, cwast.Comment)]
        result = _TypifyNodeRecursively(node.result, corpus, ctx)
        cstr = corpus.insert_fun_type(params, result)
        _AnnotateType(corpus, node, cstr)
        # recursing into the body is done explicitly
        return cstr
    elif isinstance(node, cwast.TypeArray):
        # note this is the only place where we need a comptime eval for types
        t = _TypifyNodeRecursively(node.type, corpus, ctx)
        ctx.push_target(corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.UINT))
        _TypifyNodeRecursively(node.size, corpus, ctx)
        ctx.pop_target()
        dim = _ComputeArrayLength(node.size)
        return _AnnotateType(corpus, node, corpus.insert_array_type(dim, t))
    elif isinstance(node, cwast.RecField):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        if not isinstance(node.initial_or_undef, cwast.ValUndef):
            ctx.push_target(cstr)
            _TypifyNodeRecursively(node.initial_or_undef, corpus, ctx)
            ctx.pop_target()
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.DefRec):
        # allow recursive definitions referring back to rec inside
        # the fields
        cstr = corpus.insert_rec_type(node.name, node)
        _AnnotateType(corpus, node, cstr)
        for f in node.fields:
            _TypifyNodeRecursively(f, corpus, ctx)
        # we delay this until after fields have been typified
        corpus.set_size_and_offset_for_rec_type(node)
        return cstr
    elif isinstance(node, cwast.EnumVal):
        cstr = ctx.get_target_type()
        if not isinstance(node.value_or_auto, cwast.ValAuto):
            cstr = _TypifyNodeRecursively(node.value_or_auto, corpus, ctx)
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.DefEnum):
        cstr = corpus.insert_enum_type(
            f"{ctx.mod_name}/{node.name}", node)
        base_type = corpus.insert_base_type(node.base_type_kind)
        ctx.push_target(cstr)
        for f in node.items:
            if not isinstance(f, cwast.Comment):
                _TypifyNodeRecursively(f, corpus, ctx)
        ctx.pop_target()
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.DefType):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        if node.wrapped:
            cstr = corpus.insert_wrapped_type(cstr)
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.TypeSum):
        # this is tricky code to ensure that children of TypeSum
        # are not TypeSum themselves on the canonical side
        pieces = [_TypifyNodeRecursively(f, corpus, ctx) for f in node.types]
        return _AnnotateType(corpus, node, corpus.insert_sum_type(pieces))
    if isinstance(node, (cwast.ValTrue, cwast.ValFalse)):
        return _AnnotateType(corpus, node, corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.BOOL))
    elif isinstance(node, cwast.ValVoid):
        return _AnnotateType(corpus, node, corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.VOID))
    elif isinstance(node, cwast.ValUndef):
        assert False, "Must not try to typify UNDEF"
    elif isinstance(node, cwast.ValNum):
        cstr = corpus.num_type(node.number)
        if cstr != types.NO_TYPE:
            return _AnnotateType(corpus, node, cstr)
        return _AnnotateType(corpus, node, ctx.get_target_type())
    elif isinstance(node, cwast.TypeAuto):
        assert False, "Must not try to typify TypeAuto"
    elif isinstance(node, cwast.ValAuto):
        assert False, "Must not try to typify ValAuto"
    elif isinstance(node, cwast.IndexVal):
        cstr = ctx.get_target_type()
        if not isinstance(node.value_or_undef, cwast.ValUndef):
            _TypifyNodeRecursively(node.value_or_undef, corpus, ctx)
        if not isinstance(node.init_index, cwast.ValAuto):
            ctx.push_target(corpus.insert_base_type(
                cwast.BASE_TYPE_KIND.UINT))
            _TypifyNodeRecursively(node.init_index, corpus, ctx)
            ctx.pop_target()
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.ValArray):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        ctx.push_target(cstr)
        for x in node.inits_array:
            if isinstance(x, cwast.IndexVal):
                _TypifyNodeRecursively(x, corpus, ctx)
        ctx.pop_target()
        ctx.push_target(corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.UINT))
        _TypifyNodeRecursively(node.expr_size, corpus, ctx)
        ctx.pop_target()
        dim = _ComputeArrayLength(node.expr_size)
        return _AnnotateType(corpus, node, corpus.insert_array_type(dim, cstr))
    elif isinstance(node, cwast.ValRec):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        assert isinstance(cstr, cwast.DefRec)
        all_fields: List[cwast.RecField] = [
            f for f in cstr.fields if isinstance(f, cwast.RecField)]
        for val in node.inits_rec:
            if not isinstance(val, cwast.FieldVal):
                continue
            if val.init_field:
                while True:
                    field_node = all_fields.pop(0)
                    if val.init_field == field_node.name:
                        break
            else:
                field_node = all_fields.pop(0)
            # TODO: make sure this link is set
            field_cstr = field_node.x_type
            _AnnotateField(val, field_node)
            _AnnotateType(corpus, val, field_cstr)
            ctx.push_target(field_cstr)
            _TypifyNodeRecursively(val.value, corpus, ctx)
            ctx.pop_target()
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.ValString):
        dim = ComputeStringSize(node.raw, node.string)
        cstr = corpus.insert_array_type(
            dim, corpus.insert_base_type(cwast.BASE_TYPE_KIND.U8))
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.ExprIndex):
        ctx.push_target(corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.UINT))
        _TypifyNodeRecursively(node.expr_index, corpus, ctx)
        ctx.pop_target()
        cstr = _TypifyNodeRecursively(node.container, corpus, ctx)
        return _AnnotateType(corpus, node, types.get_contained_type(cstr))
    elif isinstance(node, cwast.ExprField):
        cstr = _TypifyNodeRecursively(node.container, corpus, ctx)
        field_node = corpus.lookup_rec_field(cstr, node.field)
        _AnnotateField(node, field_node)
        return _AnnotateType(corpus, node, field_node.x_type)
    elif isinstance(node, (cwast.DefVar, cwast.DefGlobal)):
        cstr = (types.NO_TYPE if isinstance(node.type_or_auto, cwast.TypeAuto)
                else _TypifyNodeRecursively(node.type_or_auto, corpus, ctx))
        initial_cstr = types.NO_TYPE
        if not isinstance(node.initial_or_undef, cwast.ValUndef):
            ctx.push_target(cstr)
            initial_cstr = _TypifyNodeRecursively(
                node.initial_or_undef, corpus, ctx)
            ctx.pop_target()
        if cstr == types.NO_TYPE:
            cstr = initial_cstr
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.ExprDeref):
        cstr = _TypifyNodeRecursively(node.expr, corpus, ctx)
        assert isinstance(cstr, cwast.TypePtr)
        # TODO: how is mutability propagated?
        return _AnnotateType(corpus, node, cstr.type)
    elif isinstance(node, cwast.Expr1):
        cstr = _TypifyNodeRecursively(node.expr, corpus, ctx)
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.Expr2):
        cstr = _TypifyNodeRecursively(node.expr1, corpus, ctx)
        if node.binary_expr_kind in cwast.BINOP_OPS_HAVE_SAME_TYPE and types.is_number(cstr):
            ctx.push_target(cstr)
            cstr2 = _TypifyNodeRecursively(node.expr2, corpus, ctx)
            ctx.pop_target()
        else:
            cstr2 = _TypifyNodeRecursively(node.expr2, corpus, ctx)

        if node.binary_expr_kind in cwast.BINOP_BOOL:
            cstr = corpus.insert_base_type(cwast.BASE_TYPE_KIND.BOOL)
        elif node.binary_expr_kind is cwast.BINARY_EXPR_KIND.PDELTA:
            if isinstance(cstr, cwast.TypePtr):
                assert isinstance(cstr2, cwast.TypePtr)
                cstr = corpus.insert_base_type(cwast.BASE_TYPE_KIND.SINT)
            elif isinstance(cstr, cwast.TypeSlice):
                assert isinstance(cstr2, cwast.TypeSlice)
            else:
                assert False
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.Expr3):
        _TypifyNodeRecursively(node.cond, corpus, ctx)
        cstr = _TypifyNodeRecursively(node.expr_t, corpus, ctx)
        ctx.push_target(cstr)
        _TypifyNodeRecursively(node.expr_f, corpus, ctx)
        ctx.pop_target()
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.StmtExpr):
        _TypifyNodeRecursively(node.expr, corpus, ctx)
        return types.NO_TYPE
    elif isinstance(node, cwast.ExprCall):
        if node.polymorphic:
            assert len(node.args) > 0
            assert isinstance(node.callee, cwast.Id)
            t = _TypifyNodeRecursively(node.args[0], corpus, ctx)
            called_fun = ctx._poly_map.Resolve(node.callee.name, t)
            node.callee.x_symbol = called_fun
            node.callee.x_type = called_fun.x_type
            cstr = called_fun.x_type
            assert isinstance(cstr, cwast.TypeFun), f"{cstr}"
            assert len(cstr.params) == len(node.args)
            # we already process the first arg
            for p, a in zip(cstr.params[1:], node.args[1:]):
                ctx.push_target(p.type)
                _TypifyNodeRecursively(a, corpus, ctx)
                ctx.pop_target()
            return _AnnotateType(corpus, node, cstr.result)
        else:
            cstr = _TypifyNodeRecursively(node.callee, corpus, ctx)
            assert isinstance(cstr, cwast.TypeFun)
            if len(cstr.params) != len(node.args):
                cwast.CompilerError(node.x_srcloc, 
                f"number of args does not match for call to {node.callee}")
            for p, a in zip(cstr.params, node.args):
                ctx.push_target(p.type)
                _TypifyNodeRecursively(a, corpus, ctx)
                ctx.pop_target()
            return _AnnotateType(corpus, node, cstr.result)
    elif isinstance(node, cwast.StmtReturn):
        cstr = ctx.enclosing_fun.result.x_type
        ctx.push_target(cstr)
        _TypifyNodeRecursively(node.expr_ret, corpus, ctx)
        ctx.pop_target()
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtIf):
        ctx.push_target(corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.BOOL))
        _TypifyNodeRecursively(node.cond, corpus, ctx)
        ctx.pop_target()
        for c in node.body_f:
            _TypifyNodeRecursively(c, corpus, ctx)
        for c in node.body_t:
            _TypifyNodeRecursively(c, corpus, ctx)
        return types.NO_TYPE
    elif isinstance(node, cwast.Case):
        ctx.push_target(corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.BOOL))
        _TypifyNodeRecursively(node.cond, corpus, ctx)
        ctx.pop_target()
        for c in node.body:
            _TypifyNodeRecursively(c, corpus, ctx)
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtCond):
        for c in node.cases:
            _TypifyNodeRecursively(c, corpus, ctx)
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtBlock):
        for c in node.body:
            _TypifyNodeRecursively(c, corpus, ctx)
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtBreak):
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtContinue):
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtTrap):
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtAssignment):
        var_cstr = _TypifyNodeRecursively(node.lhs, corpus, ctx)
        ctx.push_target(var_cstr)
        _TypifyNodeRecursively(node.expr, corpus, ctx)
        ctx.pop_target()
        return types.NO_TYPE
    elif isinstance(node, cwast.StmtCompoundAssignment):
        var_cstr = _TypifyNodeRecursively(node.lhs, corpus, ctx)
        ctx.push_target(var_cstr)
        _TypifyNodeRecursively(node.expr, corpus, ctx)
        ctx.pop_target()
        return types.NO_TYPE
    elif isinstance(node, (cwast.ExprAs, cwast.ExprBitCast, cwast.ExprUnsafeCast)):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        _TypifyNodeRecursively(node.expr, corpus, ctx)
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, cwast.ExprAsNot):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        union = _TypifyNodeRecursively(node.expr, corpus, ctx)
        return _AnnotateType(corpus, node, corpus.insert_sum_complement(union, cstr))
    elif isinstance(node, cwast.ExprIs):
        _TypifyNodeRecursively(node.type, corpus, ctx)
        _TypifyNodeRecursively(node.expr, corpus, ctx)
        return _AnnotateType(corpus, node, corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.BOOL))
    elif isinstance(node, cwast.ExprLen):
        _TypifyNodeRecursively(node.container, corpus, ctx)
        return _AnnotateType(corpus, node, corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.UINT))
    elif isinstance(node, cwast.ExprAddrOf):
        cstr_expr = _TypifyNodeRecursively(node.expr, corpus, ctx)
        return _AnnotateType(corpus, node, corpus.insert_ptr_type(node.mut, cstr_expr))
    elif isinstance(node, cwast.ExprOffsetof):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        field_node = corpus.lookup_rec_field(cstr, node.field)
        _AnnotateField(node, field_node)
        return _AnnotateType(corpus, node, corpus.insert_base_type(cwast.BASE_TYPE_KIND.UINT))
    elif isinstance(node, cwast.ExprSizeof):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        return _AnnotateType(corpus, node, corpus.insert_base_type(cwast.BASE_TYPE_KIND.UINT))
    elif isinstance(node, cwast.ExprTryAs):
        cstr = _TypifyNodeRecursively(node.type, corpus, ctx)
        _TypifyNodeRecursively(node.expr, corpus, ctx)
        if not isinstance(node.default_or_undef, cwast.ValUndef):
            _TypifyNodeRecursively(node.default_or_undef, corpus, ctx)
        return _AnnotateType(corpus, node, cstr)
    elif isinstance(node, (cwast.StmtStaticAssert)):
        ctx.push_target(corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.BOOL))
        _TypifyNodeRecursively(node.cond, corpus, ctx)
        ctx.pop_target()
        return types.NO_TYPE
    elif isinstance(node, cwast.Import):
        return types.NO_TYPE
    else:
        assert False, f"unexpected node {node}"


UNTYPED_NODES_TO_BE_TYPECHECKED = (
    cwast.StmtReturn, cwast.StmtIf,
    cwast.StmtAssignment, cwast.StmtCompoundAssignment, cwast.StmtExpr)


def _TypeMismatch(corpus: types.TypeCorpus, msg: str, actual, expected):
    return f"{msg}: actual: {corpus.canon_name(actual)} expected: {corpus.canon_name(expected)}"


def _TypeVerifyNode(node: cwast.ALL_NODES, corpus: types.TypeCorpus, enclosing_fun):
    assert (cwast.NF.TYPE_ANNOTATED in node.__class__.FLAGS or isinstance(
        node, UNTYPED_NODES_TO_BE_TYPECHECKED))

    if isinstance(node, cwast.ValArray):
        cstr = node.type.x_type
        for x in node.inits_array:
            if isinstance(x, cwast.IndexVal):
                if not isinstance(x.init_index, cwast.ValAuto):
                    assert types.is_int(x.init_index.x_type)
                assert cstr == x.x_type, _TypeMismatch(
                    corpus, "type mismatch {x}:", x.x_type, cstr)
    elif isinstance(node, cwast.ValRec):
        for x in node.inits_rec:
            if isinstance(x, cwast.FieldVal):
                field_node = x.x_field
                assert field_node.x_type == x.x_type
    elif isinstance(node, cwast.RecField):
        if not isinstance(node.initial_or_undef, cwast.ValUndef):
            type_cstr = node.type.x_type
            initial_cstr = node.initial_or_undef.x_type
            assert types.is_compatible(
                initial_cstr, type_cstr),  _TypeMismatch(
                    corpus, f"type mismatch {node}:", initial_cstr, type_cstr)
    elif isinstance(node, cwast.ExprIndex):
        cstr = node.x_type
        assert cstr == types.get_contained_type(node.container.x_type)
    elif isinstance(node, cwast.ExprField):
        cstr = node.x_type
        field_node = node.x_field
        assert cstr == field_node.x_type
    elif isinstance(node, (cwast.DefVar, cwast.DefGlobal)):
        cstr = node.x_type
        if not isinstance(node.initial_or_undef, cwast.ValUndef):
            initial_cstr = node.initial_or_undef.x_type
            assert types.is_compatible_for_defvar(initial_cstr, cstr, types.is_mutable_def(node.initial_or_undef)), _TypeMismatch(
                corpus, f"incompatible types", initial_cstr, cstr)
        if not isinstance(node.type_or_auto, cwast.TypeAuto):
            type_cstr = node.type_or_auto.x_type
            assert cstr == type_cstr, _TypeMismatch(f"{node}", cstr, type_cstr)
    elif isinstance(node, cwast.ExprDeref):
        cstr = node.x_type
        assert cstr == node.expr.x_type.type
    elif isinstance(node, cwast.Expr1):
        cstr = node.x_type
        assert cstr == node.expr.x_type
    elif isinstance(node, cwast.Expr2):
        cstr = node.x_type
        cstr1 = node.expr1.x_type
        cstr2 = node.expr2.x_type
        if node.binary_expr_kind in cwast.BINOP_BOOL:
            assert cstr1 == cstr2, _TypeMismatch(
                corpus, f"binop mismatch in {node}:", cstr1, cstr2)
            assert types.is_bool(cstr)
        elif node.binary_expr_kind in (cwast.BINARY_EXPR_KIND.INCP,
                                       cwast.BINARY_EXPR_KIND.DECP):
            # TODO: check for pointer or slice
            assert cstr == cstr1
            assert types.is_int(cstr2)
        elif node.binary_expr_kind is cwast.BINARY_EXPR_KIND.PDELTA:
            if isinstance(cstr1, cwast.TypePtr):
                assert (isinstance(cstr2, cwast.TypeSlice) and
                        cstr1.type == cstr2.type)
                assert cstr == corpus.insert_base_type(
                    cwast.BASE_TYPE_KIND.SINT)
            elif isinstance(cstr1, cwast.TypeSlice):    
                assert (isinstance(cstr2, cwast.TypeSlice) and
                        cstr1.type == cstr2.type)
                assert cstr == cstr1 
            else:
                    assert False  
        else:
            assert cstr1 == cstr2, _TypeMismatch(
                corpus, f"binop mismatch in {node}:", cstr1, cstr2)
            assert cstr == cstr1, _TypeMismatch(f"in {node}", cstr, cstr1)
    elif isinstance(node, cwast.Expr3):
        cstr = node.x_type
        cstr_t = node.expr_t.x_type
        cstr_f = node.expr_f.x_type
        cstr_cond = node.cond.x_type
        assert cstr == cstr_t
        assert cstr == cstr_f
        assert types.is_bool(cstr_cond)
    elif isinstance(node, cwast.ExprCall):
        result = node.x_type
        fun = node.callee.x_type
        assert isinstance(fun, cwast.TypeFun), f"{fun}"
        assert fun.result == result
        for p, a in zip(fun.params, node.args):
            arg_cstr = a.x_type
            assert types.is_compatible(
                arg_cstr, p.type, types.is_mutable_def(a)), _TypeMismatch(corpus, f"incompatible fun arg: {a}",  arg_cstr, p.type)
    elif isinstance(node, cwast.StmtReturn):
        fun = enclosing_fun.x_type
        assert isinstance(fun, cwast.TypeFun)
        actual = node.expr_ret.x_type
        assert types.is_compatible(
            actual, fun.result),  _TypeMismatch(corpus, f"{node}", actual, fun.result)
    elif isinstance(node, cwast.StmtIf):
        assert types.is_bool(node.cond.x_type)
    elif isinstance(node, cwast.Case):
        assert types.is_bool(node.cond.x_type)
    elif isinstance(node, cwast.StmtAssignment):
        var_cstr = node.lhs.x_type
        expr_cstr = node.expr.x_type
        assert types.is_compatible(expr_cstr, var_cstr), _TypeMismatch(
            corpus, f"incompatible assignment: {node}",  expr_cstr, var_cstr)
        assert is_proper_lhs(node.lhs)
    elif isinstance(node, cwast.StmtCompoundAssignment):
        assert is_proper_lhs(node.lhs)
        var_cstr = node.lhs.x_type
        expr_cstr = node.expr.x_type
        if node.assignment_kind in (cwast.ASSIGNMENT_KIND.DECP, cwast.ASSIGNMENT_KIND.INCP):
            # TODO: check for pointer or slice
            assert types.is_int(expr_cstr)
        else:
            assert types.is_compatible(expr_cstr, var_cstr), _TypeMismatch(
                corpus, f"incompatible assignment arg: {node}",  expr_cstr, var_cstr)
    elif isinstance(node, cwast.StmtExpr):
        cstr = node.expr.x_type
        assert types.is_void(cstr) != node.discard
    elif isinstance(node, cwast.ExprAsNot):
        pass
    elif isinstance(node, cwast.ExprAs):
        src = node.expr.x_type
        dst = node.type.x_type
        # TODO
        # assert is_compatible_for_as(src, dst)
    elif isinstance(node, cwast.ExprUnsafeCast):
        src = node.expr.x_type
        dst = node.type.x_type
        # TODO
        # assert is_compatible_for_as(src, dst)
    elif isinstance(node, cwast.ExprBitCast):
        src = node.expr.x_type
        dst = node.type.x_type
        # TODO
        # assert is_compatible_for_as(src, dst)
    elif isinstance(node, cwast.ExprIs):
        assert types.is_bool(node.x_type)
    elif isinstance(node, cwast.ExprLen):
        assert node.x_type == corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.UINT)
    elif isinstance(node, cwast.Id):
        cstr = node.x_type
        assert cstr != types.NO_TYPE
    elif isinstance(node, cwast.ExprAddrOf):
        cstr_expr = node.expr.x_type
        cstr = node.x_type
        if node.mut:
            assert is_proper_lhs(node.expr)
        assert isinstance(cstr, cwast.TypePtr) and cstr.type == cstr_expr
    elif isinstance(node, cwast.ExprOffsetof):
        assert node.x_type == corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.UINT)
    elif isinstance(node, cwast.ExprSizeof):
        assert node.x_type == corpus.insert_base_type(
            cwast.BASE_TYPE_KIND.UINT)
    elif isinstance(node, cwast.ExprTryAs):
        cstr = node.x_type
        assert cstr == node.type.x_type, _TypeMismatch(corpus,
                                                       f"type mismatch", cstr, node.type.x_type)
        if not isinstance(node.default_or_undef, cwast.ValUndef):
            assert cstr == node.default_or_undef.x_type, _TypeMismatch(corpus,
                                                                       f"type mismatch", cstr, node.type.x_type)
        assert types.is_compatible(cstr, node.expr.x_type)
    elif isinstance(node, cwast.ValNum):
        assert isinstance(node.x_type, (cwast.TypeBase, cwast.DefEnum)
                          ), f"bad type for {node}: {node.x_type}"
    elif isinstance(node, cwast.TypeSum):
        assert isinstance(node.x_type, cwast.TypeSum)
    elif isinstance(node, (cwast.ValTrue, cwast.ValFalse, cwast.ValVoid)):
        assert isinstance(node.x_type, cwast.TypeBase)
    elif isinstance(node, (cwast.DefFun, cwast.TypeFun)):
        assert isinstance(node.x_type, cwast.TypeFun)
    elif isinstance(node, (cwast.DefType, cwast.TypeBase, cwast.TypeSlice, cwast.IndexVal,
                           cwast.TypeArray, cwast.DefFun,
                           cwast.TypePtr, cwast.FunParam, cwast.DefRec, cwast.DefEnum,
                           cwast.EnumVal, cwast.ValString, cwast.FieldVal)):
        pass
    else:
        assert False, f"unsupported  node type: {node.__class__} {node}"


def _TypeVerifyNodeRecursively(node, corpus, enclosing_fun):
    if isinstance(node, (cwast.Comment, cwast.DefMacro)):
        return
    logger.info(f"VERIFYING {node}")

    if isinstance(node, cwast.DefFun):
        enclosing_fun = node
    if (cwast.NF.TYPE_ANNOTATED in node.__class__.FLAGS or
            isinstance(node, UNTYPED_NODES_TO_BE_TYPECHECKED)):
        if cwast.NF.TYPE_ANNOTATED in node.__class__.FLAGS:
            assert node.x_type is not None, f"untyped node: {node}"
        _TypeVerifyNode(node, corpus, enclosing_fun)

    if cwast.NF.FIELD_ANNOTATED in node.__class__.FLAGS:
        assert node.x_field is not None, f"node withou field annotation: {node}"
    for c in node.__class__.FIELDS:
        nfd = cwast.ALL_FIELDS_MAP[c]
        if nfd.kind is cwast.NFK.NODE:
            _TypeVerifyNodeRecursively(getattr(node, c), corpus, enclosing_fun)
        elif nfd.kind is cwast.NFK.LIST:
            for cc in getattr(node, c):
                _TypeVerifyNodeRecursively(cc, corpus, enclosing_fun)


def DecorateASTWithTypes(mod_topo_order: List[cwast.DefMod],
                         mod_map: Dict[str, cwast.DefMod], type_corpus: types.TypeCorpus):
    """This checks types and maps them to a cananical node

    Since array type include a fixed bound this also also includes
    the evaluation of constant expressions.

    The following node fields will be initialized:
    * x_type
    * x_field
    * some x_value (only array dimention as they are related to types)
    """
    poly_map = _PolyMap(type_corpus)
    for m in mod_topo_order:
        ctx = _TypeContext(m, poly_map)
        for node in mod_map[m].body_mod:
            if not isinstance(node, (cwast.Comment, cwast.DefMacro)):
                # Note: we do not recurse into function bodies
                cstr = _TypifyNodeRecursively(node, type_corpus, ctx)
                if isinstance(node, cwast.DefFun) and node.polymorphic:
                    assert isinstance(cstr, cwast.TypeFun)
                    poly_map.Register(node)

    for m in mod_topo_order:
        ctx = _TypeContext(m, poly_map)
        for node in mod_map[m].body_mod:
            if isinstance(node, cwast.DefFun) and not node.extern:
                save_fun = ctx.enclosing_fun
                ctx.enclosing_fun = node
                for c in node.body:
                    _TypifyNodeRecursively(c, type_corpus, ctx)
                ctx.enclosing_fun = save_fun

    for m in mod_topo_order:
        _TypeVerifyNodeRecursively(mod_map[m], type_corpus, None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARN)
    logger.setLevel(logging.INFO)
    asts = cwast.ReadModsFromStream(sys.stdin)

    mod_topo_order, mod_map = symbolize.ModulesInTopologicalOrder(asts)
    symbolize.DecorateASTWithSymbols(mod_topo_order, mod_map)
    type_corpus = types.TypeCorpus(
        cwast.BASE_TYPE_KIND.U64, cwast.BASE_TYPE_KIND.S64)
    DecorateASTWithTypes(mod_topo_order, mod_map, type_corpus)

    for t in type_corpus.corpus:
        print(t)