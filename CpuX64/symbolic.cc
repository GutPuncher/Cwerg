
#include "CpuX64/symbolic.h"
#include <cstring>
#include "Util/assert.h"
#include "Util/parse.h"

namespace cwerg::x64 {
using namespace cwerg;

const char Regnames8[16][8] = {
    "al",  "cl",  "dl",   "bl",   "spl",  "bpl",  "sil",  "dil",  //
    "r8b", "r9b", "r10b", "r11b", "r12b", "r13b", "r14b", "r15b"};

const char Regnames16[16][8] = {
    "ax",  "cx",  "dx",   "bx",   "sp",   "bp",   "si",   "di",  //
    "r8w", "r9w", "r10w", "r11w", "r12w", "r13w", "r14w", "r15w"};

const char Regnames32[16][8] = {
    "eax", "ecx", "edx",  "ebx",  "esp",  "ebp",  "esi",  "edi",  //
    "r8d", "r9d", "r10d", "r11d", "r12d", "r13d", "r14d", "r15d"};

const char Regnames64[16][8] = {
    "rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",  //
    "r8",  "r9",  "r10", "r11", "r12", "r13", "r14", "r15"};

const char XRegnames[16][8] = {
    "xmm0", "xmm1", "xmm2",  "xmm3",  "xmm4",  "xmm5",  "xmm6",  "xmm7",  //
    "xmm8", "xmm9", "xmm10", "xmm11", "xmm12", "xmm13", "xmm14", "xmm15"};

const char* SymbolizeOperand(char* buf,
                             int64_t val,
                             OK ok,
                             bool show_implicits,
                             bool objdump_compat) {
  switch (ok) {
    case OK::IMPLICIT_AL:
      return show_implicits ? "al" : nullptr;
    case OK::IMPLICIT_AX:
      return show_implicits ? "ax" : nullptr;
    case OK::IMPLICIT_EAX:
      return show_implicits ? "eax" : nullptr;
    case OK::IMPLICIT_RAX:
      return show_implicits ? "rax" : nullptr;
    case OK::IMPLICIT_DX:
      return show_implicits ? "dx" : nullptr;
    case OK::IMPLICIT_EDX:
      return show_implicits ? "edx" : nullptr;
    case OK::IMPLICIT_RDX:
      return show_implicits ? "rdx" : nullptr;
    case OK::IMPLICIT_CL:
      return show_implicits ? "cl" : nullptr;
    case OK::IMPLICIT_1:
      return show_implicits ? "1" : nullptr;
    case OK::MODRM_RM_XREG32:
    case OK::MODRM_RM_XREG64:
    case OK::MODRM_RM_XREG128:
    case OK::MODRM_XREG32:
    case OK::MODRM_XREG64:
    case OK::MODRM_XREG128:
      return XRegnames[val];
    case OK::MODRM_RM_REG8:
    case OK::MODRM_REG8:
    case OK::BYTE_WITH_REG8:
      return Regnames8[val];
    case OK::MODRM_RM_REG16:
    case OK::MODRM_REG16:
    case OK::BYTE_WITH_REG16:
      return Regnames16[val];
    case OK::MODRM_RM_REG32:
    case OK::MODRM_REG32:
    case OK::BYTE_WITH_REG32:
      return Regnames32[val];
    case OK::MODRM_RM_REG64:
    case OK::MODRM_REG64:
    case OK::BYTE_WITH_REG64:
    case OK::MODRM_RM_BASE:
    case OK::SIB_BASE:
      return Regnames64[val];
    case OK::RIP_BASE:
      return "rip";
    case OK::SIB_INDEX_AS_BASE: {
      if (val == 4)
        return "nobase";
      else
        return Regnames64[val];
    }
    case OK::SIB_INDEX: {
      if (val == 4)
        return "noindex";
      else
        return Regnames64[val];
    }
    case OK::SIB_SCALE:
      if (objdump_compat) {
        ToDecSignedString(1 << val, buf);
      } else {
        ToDecSignedString(val, buf);
      }
      return buf;
    case OK::OFFPCREL8:
    case OK::OFFPCREL32:
    case OK::OFFABS8:
    case OK::OFFABS32:
      if (objdump_compat) {
        if (val >= 0) {
          buf[0] = '0';
          buf[1] = 'x';
          ToHexString(val, buf + 2);
        } else {
          buf[0] = '-';
          buf[1] = '0';
          buf[2] = 'x';
          ToHexString(-val, buf + 3);
        }
      } else {
        ToDecSignedString(val, buf);
      }
      return buf;
    case OK::IMM8:
    case OK::IMM16:
    case OK::IMM32:
    case OK::IMM8_16:
    case OK::IMM8_32:
    case OK::IMM8_64:
    case OK::IMM32_64:
    case OK::IMM64:
      buf[0] = '0';
      buf[1] = 'x';
      ToHexString(val, buf + 2);
      return buf;
  }
  ASSERT(false, "");
  return "";
}

#if 0
void SymbolizeReloc(char* cp, const Ins& ins, uint32_t addend) {
  cp = strappend(cp, "expr:");
  switch (ins.reloc_kind) {
    case elf::RELOC_TYPE_AARCH64::JUMP26:
      ASSERT(ins.is_local_sym, "");
      cp = strappend(cp, "jump26:");
      cp = strappend(cp, ins.reloc_symbol);
      break;
    case elf::RELOC_TYPE_AARCH64::ADR_PREL_PG_HI21:
      cp = strappend(cp, ins.is_local_sym ? "loc_adr_prel_pg_hi21:": "adr_prel_pg_hi21:");
      cp = strappend(cp, ins.reloc_symbol);
      break;
    case elf::RELOC_TYPE_AARCH64::ADD_ABS_LO12_NC:
      cp = strappend(cp, ins.is_local_sym ? "loc_add_abs_lo12_nc:": "add_abs_lo12_nc:");
      cp = strappend(cp, ins.reloc_symbol);
      break;
    case elf::RELOC_TYPE_AARCH64::CALL26:
      cp = strappend(cp, "call26:");
      cp = strappend(cp, ins.reloc_symbol);
      break;
    case elf::RELOC_TYPE_AARCH64::CONDBR19:
      ASSERT(ins.is_local_sym, "");
      cp = strappend(cp, "condbr19:");
      cp = strappend(cp, ins.reloc_symbol);
      break;
    default:
      ASSERT(false, "");
  }
  if (addend != 0) {
    *cp++ = ':';
    cp = strappenddec(cp, addend);
  }
}
#endif

std::string_view InsSymbolize(const x64::Ins& ins,
                              bool show_implicits,
                              bool objdump_compat,
                              std::vector<std::string>* ops) {
  bool skip_next = false;
  char buffer[128];
  const char* s;
  for (unsigned i = 0; i < ins.opcode->num_fields; ++i) {
    const OK ok = ins.opcode->fields[i];
    if (skip_next) {
      skip_next = false;
      continue;
    }

    if (objdump_compat && ok == OK::SIB_INDEX && ins.operands[i] == 4) {
      skip_next = true;
      continue;
    }

    if (objdump_compat && (ok == OK::MODRM_RM_BASE || ok == OK::RIP_BASE ||
                           ok == OK::SIB_BASE || ok == OK::SIB_INDEX_AS_BASE)) {
      if (ins.opcode->mem_width_log > 0) {
        buffer[0] = 'M';
        buffer[1] = 'E';
        buffer[2] = 'M';
        ToDecString(4 << ins.opcode->mem_width_log, buffer + 3);
        ops->emplace_back(buffer);
      }
    }

    if (ins.has_reloc() && i == ins.reloc_pos) {
      ASSERT(false, "NYI");
      // SymbolizeReloc(buffer, ins, ins.operands[i]);
    } else {
      s = SymbolizeOperand(buffer, ins.operands[i], ok, show_implicits,
                           objdump_compat);
      if (s == nullptr) continue;
    }
    ops->emplace_back(s);
  }
  return OpcodeName(ins.opcode);
}

bool HandleRelocation(std::string_view expr, unsigned pos, Ins* ins) {
  const size_t colon_sym = expr.find(':');
  if (colon_sym == std::string_view::npos) return false;
  const std::string_view kind_name = expr.substr(0, colon_sym);
  std::string_view rest = expr.substr(colon_sym + 1);
  const size_t colon_addend = rest.find(':');
  const std::string_view symbol = rest.substr(0, colon_addend);

  if (kind_name == "pcrel8") {
    ins->set_reloc(elf::RELOC_TYPE_X86_64::PC8, false, pos, symbol);
  } else if (kind_name == "pcrel32") {
    ins->set_reloc(elf::RELOC_TYPE_X86_64::PC32, false, pos, symbol);
  } else if (kind_name == "loc_pcrel8") {
    ins->set_reloc(elf::RELOC_TYPE_X86_64::PC8, true, pos, symbol);
  } else if (kind_name == "loc_pcrel32") {
    ins->set_reloc(elf::RELOC_TYPE_X86_64::PC32, true, pos, symbol);
  } else if (kind_name == "abs32") {
    ins->set_reloc(elf::RELOC_TYPE_X86_64::X_32, false, pos, symbol);
  } else if (kind_name == "abs64") {
    ins->set_reloc(elf::RELOC_TYPE_X86_64::X_64, false, pos, symbol);
  } else {
    return false;
  }
  uint64_t addend = 0;
  if (colon_addend != std::string_view::npos) {
    auto val = ParseInt<int64_t>(rest.substr(colon_addend + 1));
    if (!val.has_value()) return false;
    addend = val.value();
  }
  ins->operands[pos] = addend;

  return true;
}

bool ParseReg(std::string_view op, int64_t* val, const char names[16][8]) {
  for (uint32_t i  =0; i < 16; ++i) {
    if (op == names[i]) {
      *val = i;
      return true;
    }
  }
  return false;
}


bool UnsymbolizeOperand(OK ok, std::string_view op, int64_t* val) {
  switch (ok) {
    case OK::IMPLICIT_AL:
      *val = 0;
      return op == "al";
    case OK::IMPLICIT_AX:
      *val = 0;
      return op == "ax";
    case OK::IMPLICIT_EAX:
      *val = 0;
      return op == "eax";
    case OK::IMPLICIT_RAX:
      *val = 0;
      return op == "rax";
    case OK::IMPLICIT_DX:
      *val = 0;
      return op == "dx";
    case OK::IMPLICIT_EDX:
      *val = 0;
      return op == "edx";
    case OK::IMPLICIT_RDX:
      *val = 0;
      return op == "rdx";
    case OK::IMPLICIT_CL:
      *val = 0;
      return op == "cl";
    case OK::IMPLICIT_1: {
      *val = 0;
      auto maybe = ParseInt64(op);
      if (!maybe) return false;
      return maybe.value() == 1;
    }
    case OK::MODRM_RM_XREG32:
    case OK::MODRM_RM_XREG64:
    case OK::MODRM_RM_XREG128:
    case OK::MODRM_XREG32:
    case OK::MODRM_XREG64:
    case OK::MODRM_XREG128:
      return ParseReg(op, val, XRegnames);
    case OK::MODRM_RM_REG8:
    case OK::MODRM_REG8:
    case OK::BYTE_WITH_REG8:
      return ParseReg(op, val, Regnames8);
    case OK::MODRM_RM_REG16:
    case OK::MODRM_REG16:
    case OK::BYTE_WITH_REG16:
      return ParseReg(op, val, Regnames16);
    case OK::MODRM_RM_REG32:
    case OK::MODRM_REG32:
    case OK::BYTE_WITH_REG32:
      return ParseReg(op, val, Regnames32);
    case OK::MODRM_RM_REG64:
    case OK::MODRM_REG64:
    case OK::BYTE_WITH_REG64:
    case OK::MODRM_RM_BASE:
    case OK::SIB_BASE:
      return ParseReg(op, val, Regnames64);
    case OK::RIP_BASE:
      ASSERT(op == "rip", "");
      *val = 0;
      return true;
    case OK::SIB_INDEX_AS_BASE:
      if (op == "nobase") {
        *val = 4;
        return true;
      }
      return ParseReg(op, val, Regnames64);
    case OK::SIB_INDEX:
      if (op == "noindex") {
        *val = 4;
        return true;
      }
      return ParseReg(op, val, Regnames64);
    case OK::SIB_SCALE:
    case OK::OFFPCREL8:
    case OK::OFFPCREL32:
    case OK::OFFABS8:
    case OK::OFFABS32:
    case OK::IMM8:
    case OK::IMM16:
    case OK::IMM32:
    case OK::IMM8_16:
    case OK::IMM8_32:
    case OK::IMM8_64:
    case OK::IMM32_64:
    case OK::IMM64: {
      auto maybe = ParseInt64(op);
      if (!maybe) return false;
      *val = maybe.value();
      return true;
    }
  }
  ASSERT(false, "");
  return false;
}

bool InsFromSymbolized(const std::vector<std::string_view>& token, Ins* ins) {
  ins->opcode = FindOpcodeForMnemonic(token[0]);
  if (ins->opcode == nullptr) {
    std::cerr << "unknown opcode [" << token[0] << "]\n";
    return false;
  }
  ASSERT(token.size() - 1 == ins->opcode->num_fields,
         "bad number of token " << token.size() << " expected "
                                << ins->opcode->num_fields + 1 << " for "
                                << token[0]);
  for (unsigned i = 1; i < token.size(); ++i) {
    if (token[i].substr(0, 5) == "expr:") {
      if (!HandleRelocation(token[i].substr(5), i - 1, ins)) {
        std::cerr << "malformed relocation expression " << token[i] << "\n";
        return false;
      }
    } else {
      const OK ok = ins->opcode->fields[i - 1];
      if (!UnsymbolizeOperand(ok, token[i], (int64_t*)&ins->operands[i - 1])) {
        std::cerr << "cannot parse " << token[i] << " for ok ["
                  << EnumToString(ok) << "]\n";
        return false;
      }
    }
  }
  return true;
}

}  // namespace cwerg::x64