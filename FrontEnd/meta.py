#!/usr/bin/python3

"""Type annotator for Cwerg AST

"""

import dataclasses
import sys
import logging

from FrontEnd import cwast
from FrontEnd import symtab

from typing import List, Dict, Set, Optional, Union, Any

logger = logging.getLogger(__name__)


CanonType = str
NO_TYPE = "typeless"


class TypeContext:
    def __init__(self, symtab, mod_name):
        self.symtab: symtab.SymTab = symtab
        self.mod_name: str = mod_name
        self.enclosing_fun: Optional[cwast.DefFun] = None
        self._target_type: List[CanonType] = [NO_TYPE]

    def push_target(self, cstr: CanonType):
        self._target_type.append(cstr)

    def pop_target(self):
        self._target_type.pop(-1)

    def get_target_type(self):
        return self._target_type[-1]


TYPE_CORPUS_NODES = (cwast.DefType,  # must be `wrapped`
                     cwast.DefRec,  # uses the orginal node
                     cwast.DefEnum,  # uses the orginal node
                     cwast.TypeBase, cwast.TypePtr, cwast.TypeArray,
                     cwast.TypeSlice, cwast.TypeFun,
                     cwast.TypeSum,
                     )


class TypeCorpus:
    """The type corpus uniquifies types

    It does so by representing each type with a string (basically a serialized
    version of type like "array(ptr(u32),128)").
    That serialized version is mapped back to a structural version expressed
    using AST nodes.
    """

    def __init__(self, uint_kind, sint_kind):
        self.uint_kind = uint_kind
        self.sint_kind = sint_kind

        self.wrapped_curr = 1
        self.corpus: Dict[CanonType, Any] = {}
        self._links: Dict[int, CanonType] = {}

        for kind in cwast.BASE_TYPE_KIND:
            if kind.name in ("INVALID", "UINT", "SINT"):
                continue
            self.insert_base_type(kind)

    def _insert(self, name, node):
        assert isinstance(
            node, TYPE_CORPUS_NODES), f"not a corpus node: {node}"
        assert name not in self.corpus
        self.corpus[name] = node
        assert id(node) not in self._links
        self._links[id(node)] = name

    def insert_base_type(self, kind: cwast.BASE_TYPE_KIND) -> CanonType:
        if kind == cwast.BASE_TYPE_KIND.UINT:
            kind = self.uint_kind
        elif kind == cwast.BASE_TYPE_KIND.SINT:
            kind = self.sint_kind
        name = kind.name.lower()
        if name not in self.corpus:
            self._insert(name, cwast.TypeBase(kind))
        return name

    def insert_ptr_type(self, mut: bool, cstr: CanonType) -> CanonType:
        if mut:
            name = f"ptr-mut({cstr})"
        else:
            name = f"ptr({cstr})"
        if name not in self.corpus:
            self._insert(name, cwast.TypePtr(mut, self.corpus[cstr]))
        return name

    def insert_slice_type(self, mut: bool, cstr: CanonType) -> CanonType:
        if mut:
            name = f"slice-mut({cstr})"
        else:
            name = f"slice({cstr})"
        if name not in self.corpus:
            self._insert(name, cwast.TypeSlice(mut, self.corpus[cstr]))
        return name

    def insert_array_type(self, size: int, cstr: CanonType) -> CanonType:
        name = f"array({cstr},{size})"
        if name not in self.corpus:
            self._insert(name, cwast.TypeArray(size, self.corpus[cstr]))
        return name

    def get_children_types(self, cstr: CanonType) -> List[CanonType]:
        out: List[CanonType] = []
        cstr = cstr.split("(", 1)[1][:-1]
        open_paren = 0
        start = 0
        for n, c in enumerate(cstr):
            if c == ',' and open_paren == 0:
                out.append(cstr[start:n])
                start = n+1
            elif c == '(':
                open_paren += 1
            elif c == ")":
                open_paren -= 1
        out.append(cstr[start:])
        return out

    def get_contained_type(self, cstr: CanonType):
        if cstr.startswith("array("):
            return cstr[6:].rsplit(",", 1)[0]
        elif cstr.startswith("slice("):
            return cstr[6:-1]
        else:
            assert False

    def lookup_rec_field(self, rec_cstr: CanonType, field_name):
        """Oddball since the node returned is NOT inside corpus

        See implementation of insert_rec_type
        """
        node = self.corpus[rec_cstr]
        assert isinstance(node, cwast.DefRec)
        for x in node.fields:
            if isinstance(x, cwast.RecField) and x.name == field_name:
                return x
        assert False

    def get_pointee_type(self, cstr: CanonType):
        assert cstr.startswith("ptr")
        return cstr.split("(", 1)[:-1]

    def insert_rec_type(self, name: str, node) -> CanonType:
        name = f"rec({name})"
        if name not in self.corpus:
            assert isinstance(node, cwast.DefRec), f"{name} {node}"
            self._insert(name, node)
        return name

    def insert_enum_type(self, name: str, node) -> CanonType:
        assert isinstance(node, cwast.DefEnum)
        name = f"enum({name})"
        if name not in self.corpus:
            self._insert(name, node)
        return name

    def insert_sum_type(self, components: List[CanonType]) -> CanonType:
        pieces = []
        for c in components:
            node = self.corpus[c]
            if isinstance(node, cwast.TypeSum):
                for cc in node.types:
                    pieces.append(cc)
            else:
                pieces.append(node)
        pp = sorted(self._links[id(p)] for p in pieces)
        name = f"sum({','.join(pp)})"
        if name not in self.corpus:
            self._insert(name, cwast.TypeSum(pieces))
        return name

    def insert_fun_type(self, params: List[CanonType], result: CanonType) -> CanonType:
        name = f"fun({','.join(params +[result])})"
        if name not in self.corpus:
            p = [cwast.FunParam("", self.corpus[x]) for x in params]
            self._insert(name, cwast.TypeFun(p, self.corpus[result]))
        return name

    def insert_wrapped_type(self, cstr: CanonType, node) -> CanonType:
        assert isinstance(node, cwast.DefType)
        uid = self.wrapped_curr
        self.wrapped_curr += 1
        name = f"wrapped({uid},{cstr})"
        assert name not in self.corpus
        self._insert(name, node)
        return name


def ComputeStringSize(noesc: bool, string: str) -> int:
    assert string[0] == '"'
    assert string[-1] == '"'
    string = string[1:-1]
    n = len(string)
    if noesc:
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



TYPED_ANNOTATED_NODES = TYPE_CORPUS_NODES + cwast.VALUE_NODES + (
    cwast.FunParam,
    cwast.RecField,
    cwast.EnumEntry,
    cwast.DefFun,
    cwast.DefVar,
    cwast.StmtFor,
    cwast.DefConst,
    #
    cwast.Id,
    #
    cwast. ExprAddrOf, cwast.ExprDeref, cwast.ExprIndex,
    cwast.ExprField, cwast.ExprCall, cwast.ExprParen,
    cwast.Expr1, cwast.Expr2, cwast.Expr3,
    cwast.ExprUnwrap, cwast.ExprChop,
    cwast.ExprLen, cwast.ExprSizeof,
    cwast.ExprRange,
    #
)


class TypeTab:
    """Type Table

    Requires SymTab info to resolve DefType symnbols
    """

    def __init__(self, uint_kind, sint_kind):
        self.wrapped_curr = 1
        self.corpus = TypeCorpus(uint_kind, sint_kind)
        self.dims: Dict[int, int] = {}
        self.links: Dict[int, CanonType] = {}

    def link(self, node) -> CanonType:
        return self.links[id(node)]

    def compute_dim(self, node) -> int:
        assert isinstance(node, cwast.ValNum), f"unexpected number: {node}"
        return int(node.number)

    def annotate(self, node, cstr: CanonType):
        assert isinstance(
            node, TYPED_ANNOTATED_NODES), f"node not meant for type annotation: {node}"
        assert cstr, f"No valid type for {node}"
        assert id(node) not in self.links, f"duplicate annotation for {node}"
        self.links[id(node)] = cstr
        return cstr

    def num_type(self, num: str) -> CanonType:
        for x in ("s8", "s16", "s32", "s64", "u8", "u16", "u32", "u64", "r32", "r64"):
            if num.endswith(x):
                return x
        if num.endswith("sint"):
            return cwast.BASE_TYPE_KIND.SINT.name.lower()
        elif num.endswith("uint"):
            return cwast.BASE_TYPE_KIND.UINT.name.lower()
        else:
            return NO_TYPE

    def typify_node(self, node,  ctx: TypeContext) -> CanonType:
        target_type = ctx.get_target_type()
        extra = "" if target_type == NO_TYPE else f"[{target_type}]"
        logger.info(f"TYPIFYING{extra} {node}")
        cstr = self.links.get(id(node))
        if cstr is not None:
            # has been typified already
            return cstr
        if isinstance(node, cwast.Comment):
            return NO_TYPE
        elif isinstance(node, cwast.Id):
            # this case is why we need the sym_tab
            def_node = ctx.symtab.get_definition_for_symbol(node)
            # assert isinstance(def_node, cwast.DefType), f"unexpected node {def_node}"
            cstr = self.typify_node(def_node, ctx)
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.TypeBase):
            return self.annotate(node, self.corpus.insert_base_type(node.base_type_kind))
        elif isinstance(node, cwast.TypePtr):
            t = self.typify_node(node.type, ctx)
            return self.annotate(node, self.corpus.insert_ptr_type(node.mut, t))
        elif isinstance(node, cwast.TypeSlice):
            t = self.typify_node(node.type, ctx)
            return self.annotate(node, self.corpus.insert_slice_type(node.mut, t))
        elif isinstance(node, (cwast.FunParam, cwast.RecField)):
            cstr = self.typify_node(node.type, ctx)
            return self.annotate(node, cstr)
        elif isinstance(node, (cwast.TypeFun, cwast.DefFun)):
            params = [self.typify_node(p, ctx)
                      for p in node.params if not isinstance(p, cwast.Comment)]
            result = self.typify_node(node.result, ctx)
            cstr = self.corpus.insert_fun_type(params, result)
            self.annotate(node, cstr)
            if isinstance(node, cwast.DefFun) and not node.extern:
                save_fun = ctx.enclosing_fun
                ctx.enclosing_fun = node
                for c in node.body:
                    self.typify_node(c, ctx)
                ctx.enclosing_fun = save_fun
            return cstr
        elif isinstance(node, cwast.TypeArray):
            # note this is the only place where we need a comptime eval
            t = self.typify_node(node.type, ctx)
            dim = self.compute_dim(node.size)
            return self.annotate(node, self.corpus.insert_array_type(dim, t))
        elif isinstance(node, cwast.RecField):
            t = self.typify_node(f.type, ctx)
            return self.annotate(node, t)
        elif isinstance(node, cwast.DefRec):
            # allow recursive definitions referring back to rec inside
            # the fields
            cstr = self.corpus.insert_rec_type(node.name, node)
            self.annotate(node, cstr)
            for f in node.fields:
                self.typify_node(f, ctx)
            return cstr
        elif isinstance(node, cwast.EnumEntry):
            cstr = ctx.get_target_type()
            if not isinstance(node.value, cwast.Auto):
                cstr = self.typify_node(node.value, ctx)
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.DefEnum):
            base_type = self.corpus.insert_base_type(node.base_type_kind)
            ctx.push_target(base_type)
            for f in node.items:
                self.typify_node(f, ctx)
            ctx.pop_target()
            return self.annotate(node, self.corpus.insert_enum_type(
                f"{ctx.mod_name}/{node.name}", node))
        elif isinstance(node, cwast.DefType):
            cstr = self.typify_node(node.type, ctx)
            if node.wrapped:
                cstr = self.corpus.insert_wrapped_type(cstr, node)
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.TypeSum):
            # this is tricky code to ensure that children of TypeSum
            # are not TypeSum themselves on the canonical side
            pieces = [self.typify_node(f, ctx) for f in node.types]
            return self.annotate(node, self.corpus.insert_sum_type(pieces))
        if isinstance(node, cwast.ValBool):
            return self.annotate(node, self.corpus.insert_base_type(
                cwast.TypeBase(cwast.BASE_TYPE_KIND.BOOL)))
        elif isinstance(node, cwast.ValVoid):
            return self.annotate(node, self.corpus.insert_base_type(
                cwast.BASE_TYPE_KIND.VOID))
        elif isinstance(node, cwast.ValUndef):
            return self.annotate(node, ctx.get_target_type())
        elif isinstance(node, cwast.ValNum):
            cstr = self.num_type(node.number)
            if cstr != NO_TYPE:
                return self.annotate(node, cstr)
            return self.annotate(node, ctx.get_target_type())
        elif isinstance(node, cwast.Auto):
            assert False, "Must not try to typify AUTO"
        elif isinstance(node, cwast.DefConst):
            ctx.push_target(NO_TYPE if
                            isinstance(node.type, cwast.Auto) else
                            self.typify_node(node.type, ctx))
            cstr = self.typify_node(node.value, ctx)
            ctx.pop_target()
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.IndexVal):
            cstr = self.typify_node(node.value, ctx)
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.ValArray):
            cstr = self.typify_node(node.type, ctx)
            ctx.push_target(cstr)
            for x in node.values:
                self.typify_node(x, ctx)
            ctx.pop_target()
            dim = self.compute_dim(node.size)
            return self.annotate(node, self.corpus.insert_array_type(dim, cstr))
        elif isinstance(node, cwast.FieldVal):
            cstr = self.typify_node(node.value, ctx)
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.ValRec):
            cstr = self.typify_node(node.type, ctx)
            for val in node.values:
                field_cstr = NO_TYPE
                if isinstance(val, cwast.FieldVal):
                    field = self.corpus.lookup_rec_field(cstr, val.field)
                    field_cstr = self.links[id(field)]
                ctx.push_target(field_cstr)
                self.typify_node(val, ctx)
                ctx.pop_target()
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.ValArrayString):
            dim = ComputeStringSize(node.noesc, node.string)
            cstr = self.corpus.insert_array_type(
                dim, self.corpus.insert_base_type(cwast.BASE_TYPE_KIND.U8))
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.ExprIndex):
            self.typify_node(node.expr_index, ctx)
            cstr = self.typify_node(node.container, ctx)
            return self.annotate(node, self.corpus.get_contained_type(cstr))
        elif isinstance(node, cwast.ExprField):
            cstr = self.typify_node(node.container, ctx)
            field_node = self.corpus.lookup_rec_field(cstr, node.field)
            return self.annotate(node, self.links[id(field_node)])
        elif isinstance(node, cwast.DefVar):
            ctx.push_target(NO_TYPE if
                            isinstance(node.type, cwast.Auto)
                            else self.typify_node(node.type, ctx))
            cstr = self.typify_node(node.initial, ctx)
            ctx.pop_target()
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.ExprRange):
            cstr = self.typify_node(node.end, ctx)
            if not isinstance(node.start, cwast.Auto):
                self.typify_node(node.start, ctx)
            if not isinstance(node.step, cwast.Auto):
                self.typify_node(node.step, ctx)
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.StmtFor):
            ctx.push_target(NO_TYPE if
                            isinstance(node.type, cwast.Auto)
                            else self.typify_node(node.type, ctx))
            cstr = self.typify_node(node.range, ctx)
            ctx.pop_target()
            self.annotate(node, cstr)
            for c in node.body:
                self.typify_node(c, ctx)
            return cstr
        elif isinstance(node, cwast.ExprDeref):
            cstr = self.typify_node(node.expr, ctx)
            return self.annotate(node, self.corpus.get_pointee_type(cstr))
        elif isinstance(node, cwast.Expr1):
            cstr = self.typify_node(node.expr, ctx)
            return self.annotate(node, self.corpus.get_pointee_type(cstr))
        elif isinstance(node, cwast.Expr2):
            # cstr = ctx.get_target_type()
            # Needs tons of work
            cstr = self.typify_node(node.expr1, ctx)
            self.typify_node(node.expr1, ctx)
            return cstr
        elif isinstance(node, cwast.StmtExpr):
            self.typify_node(node.expr, ctx)
            return NO_TYPE
        elif isinstance(node, cwast.ExprCall):
            cstr = self.typify_node(node.callee, ctx)
            params = self.corpus.get_children_types(cstr)
            cstr = params.pop(-1)
            assert len(params) == len(node.args)
            for p, a in zip(params, node.args):
                ctx.push_target(p)
                self.typify_node(a, ctx)
                ctx.pop_target()
            return self.annotate(node, cstr)
        elif isinstance(node, cwast.StmtReturn):
            cstr = self.links[id(ctx.enclosing_fun.result)]
            ctx.push_target(cstr)
            self.typify_node(node.expr_ret, ctx)
            ctx.pop_target()
            return NO_TYPE
        elif isinstance(node, cwast.StmtIf):
            ctx.push_target(self.corpus.insert_base_type(
                cwast.BASE_TYPE_KIND.BOOL))
            self.typify_node(node.cond, ctx)
            ctx.pop_target()
            for c in node.body_f:
                self.typify_node(c, ctx)
            for c in node.body_t:
                self.typify_node(c, ctx)
            return NO_TYPE
        elif isinstance(node, cwast.StmtBlock):
            for c in node.body:
                self.typify_node(c, ctx)
            return NO_TYPE
        elif isinstance(node, cwast.StmtBreak):
            return NO_TYPE
        elif isinstance(node, cwast.StmtContinue):
            return NO_TYPE
        else:
            assert False, f"unexpected node {node}"

    def canonicalize_type(self, node) -> str:
        pass


CanonConst = Any


class ConstTab:
    """Type Table

    Requires SymTab info to resolve DefType symnbols
    """

    def __init__(self):
        self.links = {}

    def link(self, node) -> CanonConst:
        return self.links[id(node)]

    def constify_value_node(self, node,  target_type: Optional[CanonType], mod_name,
                            sym_tab: symtab.SymTab) -> CanonType:
        logger.info(f"CONSTFYING {node}")
        assert isinstance(node, _VALUE_NODES), f"unexpected node {node}"
        if isinstance(node, cwast.Id):
            pass
            # this case is why we need the sym_tab
            def_node = sym_tab.get_definition_for_symbol(node)
            # assert isinstance(def_node, cwast.DefType), f"unexpected node {def_node}"
            cstr = self.typify_type_node(def_node, mod_name, sym_tab)
        elif isinstance(node, (cwast.ValBool, cwast.ValUndef, cwast.ValVoid)):
            self.links[id(node)] = node
        elif isinstance(node, cwast.ValNum):
            self.links[id(node)] = node


def ExtractTypeTab(asts: List, symtab: symtab.SymTab) -> TypeTab:
    """This checks types and maps them to a cananical node

    Since array type include a fixed bound this also also includes
    the evaluation of constant expressions.
    """
    typetab = TypeTab(cwast.BASE_TYPE_KIND.U32, cwast.BASE_TYPE_KIND.S32)
    for m in asts:
        ctx = TypeContext(symtab, m.name)
        for node in m.children():
            # if isinstance(node, _NODES_RELATED_TO_TYPES):
            typetab.typify_node(node, ctx)
    return typetab


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARN)
    logger.setLevel(logging.INFO)
    asts = []
    try:
        while True:
            stream = cwast.ReadTokens(sys.stdin)
            t = next(stream)
            assert t == "("
            sexpr = cwast.ReadSExpr(stream)
            # print(sexpr)
            asts.append(sexpr)
    except StopIteration:
        pass
    symtab = symtab.ExtractSymTab(asts)
    typetab = ExtractTypeTab(asts, symtab)
    for t in typetab.corpus.corpus:
        print(t)