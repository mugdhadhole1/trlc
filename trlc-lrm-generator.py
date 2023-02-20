#!/usr/bin/env python3
#
# TRLC - Treat Requirements Like Code
# Copyright (C) 2022-2023 Florian Schanda
#
# This file is part of the TRLC Python Reference Implementation.
#
# TRLC is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# TRLC is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details.
#
# You should have received a copy of the GNU General Public License
# along with TRLC. If not, see <https://www.gnu.org/licenses/>.

# pylint: disable=invalid-name

import sys
import html
import re
import os
import re

from trlc.errors import Message_Handler, TRLC_Error
from trlc.trlc import Source_Manager
from trlc.lexer import Source_Reference
from trlc import ast

BMW_BLUE_1 = "#0066B1"
BMW_BLUE_2 = "#003D78"
BMW_RED    = "#E22718"
BMW_GREY   = "#6f6f6f"
BMW_SILVER = "#d6d6d6"


class BNF_Token:
    KIND = (
        "NONTERMINAL",     # foo   foo_NAME
        "TERMINAL",        # FOO   FOO_name
        "PRODUCTION",      # ::=
        "ALTERNATIVE",     # |
        "SYMBOL",          # 'potato'
        "S_BRA", "S_KET",  # []
        "C_BRA", "C_KET",  # {}
        "RULE_END",        # two or more newlines
    )

    def __init__(self, kind, value, start, end, location):
        assert kind in BNF_Token.KIND
        assert isinstance(start, int)
        assert isinstance(end, int) and start <= end
        assert isinstance(location, Source_Reference)

        self.kind     = kind
        self.value    = value
        self.location = location
        self.start    = start
        self.end      = end

    def __repr__(self):
        return "BNF_Token(%s, %s, <loc>)" % (self.kind, self.value)


class BNF_Lexer:
    def __init__(self, mh, fragment, original_location):
        assert isinstance(mh, Message_Handler)
        assert isinstance(fragment, str)
        assert isinstance(original_location, Source_Reference)
        self.mh                = mh
        self.fragment          = fragment
        self.original_location = original_location
        self.fragment_length   = len(self.fragment)

        self.lexpos  = -2
        self.line_no = 0
        self.col_no  = 0
        self.cc = None
        self.nc = None
        self.eof_token_generated = False

        self.advance()

    def advance(self):
        self.lexpos += 1
        if self.cc == "\n" or self.lexpos == 0:
            self.line_no += 1
            self.col_no = 0
        if self.nc is not None:
            self.col_no += 1
        self.cc = self.nc
        self.nc = (self.fragment[self.lexpos + 1]
                   if self.lexpos + 1 < self.fragment_length
                   else None)

    def token(self):
        # Skip whitespace and comments
        num_nl = 0
        start_pos  = self.lexpos
        start_line = self.line_no
        start_col  = self.col_no
        while self.nc and self.nc.isspace():
            self.advance()
            if self.cc == "\n":
                num_nl += 1
        if num_nl < 2:
            self.advance()

        if self.cc is None:
            if not self.eof_token_generated:
                self.eof_token_generated = True
                return BNF_Token(kind     = "RULE_END",
                                 value    = None,
                                 start    = self.lexpos,
                                 end      = self.lexpos,
                                 location = self.mk_location(start_line,
                                                             start_col,
                                                             self.lexpos,
                                                             self.lexpos))
            return None

        # If we have more than one empty line then this is the end of
        # a rule.
        if num_nl >= 2:
            return BNF_Token(kind     = "RULE_END",
                             value    = None,
                             start    = start_pos,
                             end      = self.lexpos,
                             location = self.mk_location(self.line_no,
                                                         start_col,
                                                         start_pos,
                                                         self.lexpos))

        start_pos  = self.lexpos
        start_line = self.line_no
        start_col  = self.col_no

        if self.cc == "[":
            kind = "S_BRA"

        elif self.cc == "]":
            kind = "S_KET"

        elif self.cc == "{":
            kind = "C_BRA"

        elif self.cc == "}":
            kind = "C_KET"

        elif self.cc == "|":
            kind = "ALTERNATIVE"

        elif self.cc == ":":
            kind = "PRODUCTION"
            self.advance()
            if self.cc != ":":
                self.lex_error("malformed ::= operator")
            self.advance()
            if self.cc != "=":
                self.lex_error("malformed ::= operator")

        elif self.cc.islower():
            # Either nonterm or nonterm_NAME
            kind = "NONTERMINAL"
            while self.nc and (self.nc.isalpha() or self.nc == "_"):
                self.advance()

        elif self.cc.isupper():
            # Either TERMINAL or TERMINAL_name
            kind = "TERMINAL"
            while self.nc and (self.nc.isalpha() or self.nc == "_"):
                self.advance()

        elif self.cc == "'":
            kind = "SYMBOL"
            while self.nc and self.nc != "'":
                self.advance()
            if self.nc is None:
                self.lex_error("unclosed token literal")
            self.advance()

        else:
            self.lex_error("unexpected character %s" % self.cc)

        end_pos  = self.lexpos
        raw_text = self.fragment[start_pos:end_pos + 1]

        if kind == "TERMINAL":
            t_kind = ""
            t_name = None
            in_kind = True
            for c in raw_text:
                if in_kind and c.islower():
                    assert t_kind.endswith("_")
                    t_kind = t_kind[:-1]
                    in_kind = False
                    t_name = c
                elif in_kind:
                    t_kind += c
                else:
                    t_name += c
            value = (t_kind, t_name)

        elif kind == "NONTERMINAL":
            t_prod = ""
            t_name = None
            in_prod = True
            for c in raw_text:
                if in_prod and c.isupper():
                    assert t_prod.endswith("_")
                    t_prod = t_prod[:-1]
                    in_prod = False
                    t_name = c
                elif in_prod:
                    t_prod += c
                else:
                    t_name += c
            value = (t_prod, t_name)

        elif kind == "SYMBOL":
            value = raw_text[1:-1]

        else:
            value = None

        return BNF_Token(kind     = kind,
                         value    = value,
                         start    = start_pos,
                         end      = end_pos,
                         location = self.mk_location(start_line,
                                                     start_col,
                                                     start_pos,
                                                     end_pos))

    def mk_location(self, start_line, start_col, start_pos, end_pos):
        sref = Source_Reference(
            lexer      = self.original_location.lexer,
            start_line = self.original_location.line_no + (start_line - 1),
            start_col  = (self.original_location.col_no + 3
                          if start_line == 1
                          else start_col),
            start_pos  = self.original_location.start_pos + 3 + start_pos,
            end_pos    = self.original_location.start_pos + 3 + end_pos)
        return sref

    def lex_error(self, message):
        self.mh.error(self.mk_location(self.line_no, self.col_no,
                                       self.lexpos, self.lexpos),
                      message)


class BNF_AST_Node:
    def __init__(self, location):
        assert isinstance(location, Source_Reference)
        self.location = location


class BNF_Expansion(BNF_AST_Node):
    pass


class BNF_Literal(BNF_Expansion):
    def __init__(self, location, kind, value, name=None):
        super().__init__(location)
        assert kind in ("TERMINAL",
                        "NONTERMINAL",
                        "SYMBOL")
        assert isinstance(value, str)
        assert isinstance(name, str) or name is None

        self.kind  = kind
        self.value = value
        self.name  = name

    def __str__(self):
        return self.value


class BNF_Optional(BNF_Expansion):
    def __init__(self, location, expansion):
        super().__init__(location)
        assert isinstance(expansion, BNF_Expansion)

        self.expansion = expansion

    def __str__(self):
        return "[ %s ]" % str(self.expansion)


class BNF_One_Or_More(BNF_Expansion):
    def __init__(self, location, expansion):
        super().__init__(location)
        assert isinstance(expansion, BNF_Expansion)

        self.expansion = expansion

    def __str__(self):
        return "{ %s }" % str(self.expansion)


class BNF_String(BNF_Expansion):
    def __init__(self, members):
        assert isinstance(members, list) and len(members) >= 2
        for member in members:
            assert isinstance(member, BNF_Expansion)
        super().__init__(members[0].location)

        self.members = members

    def __str__(self):
        return " ".join(map(str, self.members))


class BNF_Alternatives(BNF_Expansion):
    def __init__(self, members):
        assert isinstance(members, list) and len(members) >= 2
        for member in members:
            assert isinstance(member, BNF_Expansion)
        super().__init__(members[0].location)

        self.members = members

    def __str__(self):
        return " | ".join(map(str, self.members))


class BNF_Parser:
    def __init__(self, mh):
        assert isinstance(mh, Message_Handler)

        self.mh = mh

        # Lexer state
        self.current_lexer = None
        self.ct            = None
        self.nt            = None

        # Symbol table
        self.terminals   = set()
        self.productions = {}
        self.bundles     = {}

    def advance(self):
        assert self.current_lexer is not None

        self.ct = self.nt
        self.nt = self.current_lexer.token()

    def error(self, token, message):
        assert isinstance(token, BNF_Token)
        assert isinstance(message, str)

        self.mh.error(token.location, message)

    def peek(self, kind):
        assert kind in BNF_Token.KIND

        return self.nt and self.nt.kind == kind

    def match(self, kind):
        assert kind in BNF_Token.KIND

        if self.nt is None:
            self.error(self.ct, "expected %s, encountered EOS instead" % kind)
        elif self.nt.kind != kind:
            self.error(self.nt, "expected %s, encountered %s instead" %
                       (kind, self.nt.kind))

        self.advance()

    def sem(self):
        for production in self.productions:
            self.sem_production(production)

    def sem_production(self, production):
        n_exp = self.productions[production]

        self.sem_expansion(n_exp)

    def sem_expansion(self, n_exp):
        assert isinstance(n_exp, BNF_Expansion)

        if isinstance(n_exp, (BNF_One_Or_More,
                              BNF_Optional)):
            self.sem_expansion(n_exp.expansion)

        elif isinstance(n_exp, (BNF_String,
                                BNF_Alternatives)):
            for n_member in n_exp.members:
                self.sem_expansion(n_member)

        else:
            self.sem_literal(n_exp)

    def sem_literal(self, n_literal):
        assert isinstance(n_literal, BNF_Literal)

        if n_literal.kind == "SYMBOL":
            if n_literal.value not in self.terminals:
                self.mh.warning(n_literal.location,
                                "unknown terminal")

        elif n_literal.kind == "TERMINAL":
            # TODO
            pass

        else:
            assert n_literal.kind == "NONTERMINAL"
            if n_literal.value not in self.productions:
                self.mh.warning(n_literal.location,
                                "unknown production")

    def register_terminal(self, obj):
        assert isinstance(obj, ast.String_Literal)

        if obj.value in self.terminals:
            self.mh.error(obj.location,
                          "duplicate definition of terminal")
        self.terminals.add(obj.value)

    def register_backtick_terminals(self, obj):
        assert isinstance(obj, ast.String_Literal)

        for match in re.finditer("`([^`]*)`", obj.value):
            terminal = match.group(1)
            if terminal:
                if terminal in self.terminals:
                    self.mh.error(obj.location,
                                  "duplicate definition of terminal '%s'" %
                                  terminal)
                else:
                    self.terminals.add(terminal)
            else:
                self.mh.error(obj.location,
                              "empty terminal is not permitted")

    def parse(self, obj):
        assert self.current_lexer is None
        assert isinstance(obj, ast.Record_Object)
        assert obj.e_typ.name == "Grammar"

        # Get original text (without the ''' whitespace
        # simplifications)
        orig_text = obj.field["bnf"].location.text()
        if not orig_text.startswith("'''"):
            self.mh.error(obj.field["bnf"].location,
                     "BNF text must use ''' strings")
        orig_text = orig_text[3:-3]

        # Create nested lexer
        self.current_lexer = BNF_Lexer(self.mh,
                                       orig_text,
                                       obj.field["bnf"].location)
        self.ct = None
        self.nt = self.current_lexer.token()

        self.bundles[obj.name] = []
        while self.nt:
            self.bundles[obj.name].append(self.parse_production())
            self.match("RULE_END")

        self.current_lexer = None
        self.ct            = None
        self.nt            = None

    def parse_production(self):
        # production ::= expansion

        self.match("NONTERMINAL")
        prod_name = self.ct.value[0]
        if prod_name in self.productions:
            self.error(self.ct, "duplicated definition")
        self.match("PRODUCTION")
        self.productions[prod_name] = self.parse_expansion()
        return prod_name

    def parse_expansion(self):
        # expansion ::= string { '|' string }
        #
        # string ::= fragment { fragment }
        #
        # fragment ::= '{' expansion '}'
        #            | '[' expansion ']'
        #            | TERMINAL
        #            | NONTERMINAL
        #            | SYMBOL

        rv = [self.parse_string()]
        while self.peek("ALTERNATIVE"):
            self.match("ALTERNATIVE")
            rv.append(self.parse_string())

        if len(rv) == 1:
            return rv[0]
        else:
            return BNF_Alternatives(rv)

    def parse_string(self):
        rv = [self.parse_fragment()]
        while self.nt.kind in ("C_BRA", "S_BRA",
                               "TERMINAL",
                               "NONTERMINAL",
                               "SYMBOL"):
            rv.append(self.parse_fragment())

        if len(rv) == 1:
            return rv[0]
        else:
            return BNF_String(rv)

    def parse_fragment(self):
        loc = self.nt.location

        if self.peek("C_BRA"):
            self.match("C_BRA")
            rv = self.parse_expansion()
            self.match("C_KET")
            return BNF_One_Or_More(loc, rv)

        elif self.peek("S_BRA"):
            self.match("S_BRA")
            rv = self.parse_expansion()
            self.match("S_KET")
            return BNF_Optional(loc, rv)

        elif self.peek("TERMINAL"):
            self.match("TERMINAL")
            return BNF_Literal(loc,
                               self.ct.kind,
                               self.ct.value[0],
                               self.ct.value[1])

        elif self.peek("NONTERMINAL"):
            self.match("NONTERMINAL")
            return BNF_Literal(loc,
                               self.ct.kind,
                               self.ct.value[0],
                               self.ct.value[1])

        elif self.peek("SYMBOL"):
            self.match("SYMBOL")
            return BNF_Literal(loc, self.ct.kind, self.ct.value)

        self.error(self.nt,
                   "expected bnf fragment")


def write_heading(fd, name, depth):
    fd.write("<h%u>%s</h%u>\n" % (depth,
                                  html.escape(name),
                                  depth))


def write_header(fd, obj_license):
    fd.write("<!DOCTYPE html>\n")
    fd.write("<html>\n")
    fd.write("<head>\n")
    fd.write("<title>TRLC Language Reference Manual</title>\n")
    fd.write("<meta name=\"viewport\" "
             "content=\"width=device-width, initial-scale=1.0\">\n")
    fd.write("<style>\n")
    fd.write("body {\n")
    fd.write("  font-family: sans;\n")
    fd.write("}\n")
    fd.write("footer {\n")
    fd.write("  color: %s;\n" % BMW_BLUE_2)
    fd.write("}\n")
    fd.write("h1, h2, h3, h4, h5, h6, h7 {\n")
    fd.write("  color: %s\n" % BMW_BLUE_2)
    fd.write("}\n")
    fd.write("div {\n")
    fd.write("  margin-top: 0.2em;\n")
    fd.write("}\n")
    fd.write("div.code {\n")
    fd.write("  margin-top: 1.5em;\n")
    fd.write("  margin-bottom: 1.5em;\n")
    fd.write("  border-radius: 1em;\n")
    fd.write("  padding: 1em;\n")
    fd.write("  background-color: %s;\n" % BMW_SILVER)
    fd.write("}\n")
    fd.write("a {\n")
    fd.write("  color: %s;\n" % BMW_BLUE_1)
    fd.write("}\n")
    fd.write("pre a {\n")
    fd.write("  text-decoration: none;\n")
    fd.write("}\n")
    fd.write("pre a:hover {\n")
    fd.write("  text-decoration: underline;\n")
    fd.write("}\n")
    fd.write("</style>\n")
    fd.write("</style>\n")
    fd.write("</head>\n")
    fd.write("<body>\n")

    write_heading(fd, "TRLC Language Reference Manual", 1)
    lic = obj_license.to_python_dict()
    fd.write("<div>\n")
    fd.write("Permission is granted to copy, distribute and/or"
             " modify this document under the terms of the GNU Free"
             " Documentation License, Version 1.3 or any later version"
             " published by the Free SoftwareFoundation;")
    if not lic["invariant_sections"]:
        fd.write(" with no Invariant Sections,")
    else:
        assert False
    if lic["front_cover"]:
        assert False
    else:
        fd.write(" no Front-Cover Texts,")
    if lic["back_cover"]:
        assert False
    else:
        fd.write(" and no Back-Cover Texts.")
    fd.write("\n")
    fd.write("A copy of the license is included in the section"
             " entitled \"Appendix A: GNU Free Documentation License\".\n")
    fd.write("</div>\n")


def write_footer(fd, script_name):
    write_heading(fd, "Appendix A: GNU Free Documentation License", 1)
    with open("language-reference-manual/LICENSE.html_fragment", "r",
              encoding="UTF-8") as fd_lic:
        fd.write(fd_lic.read())
    fd.write("</body>\n")
    fd.write("<footer>\n")
    gh_root = "https://github.com/bmw-software-engineering"
    gh_project = "trlc"
    fd.write("Generated by the <a href=\"%s/%s/blob/main/%s\">" %
             (gh_root, gh_project, script_name))
    fd.write("TRLC LRM Generator</a>\n")
    fd.write("</footer>\n")
    fd.write("</html>\n")


def section_list(section):
    assert isinstance(section, ast.Section)
    if section.parent:
        return section_list(section.parent) + [section.name]
    else:
        return [section.name]


def section_depth(section):
    assert isinstance(section, ast.Section)
    if section.parent:
        return section_depth(section.parent) + 1
    else:
        return 1


def fmt_text(text):
    text = " ".join(text.replace("\n", " ").split())
    text = html.escape(text)
    text = re.sub("`(.*?)`", "<tt>\\1</tt>", text)
    return text


def write_text_object(fd, obj, context, bnf_parser):
    data = obj.to_python_dict()

    # Build current section
    if obj.section:
        new_section = section_list(obj.section)
    else:
        new_section = []

    if obj.e_typ.name in ("Text", "Grammar",
                          "Terminal",
                          "Keywords",
                          "Punctuation"):
        pass
    elif obj.e_typ.name == "Semantics":
        new_section.append(data["kind"] + " Semantics")
    elif obj.e_typ.name == "Recommendation":
        new_section.append("Implementation Recommendation")
    elif obj.e_typ.name == "Example":
        new_section.append("Example")
    else:
        assert False

    # Generate new headings as appropriate
    if context["old_section"] is not None:
        old_section = context["old_section"]
    else:
        old_section = []
    identical = True
    for idx, heading in enumerate(new_section):
        if idx < len(old_section):
            if heading != old_section[idx]:
                identical = False
        else:
            identical = False
        if not identical:
            write_heading(fd, heading, idx + 2)

    # Store new section
    context["old_section"] = new_section

    # Emit
    fd.write("<div>\n")
    if data["text"]:
        fd.write(fmt_text(data["text"]) + "\n")
    if data["bullets"]:
        fd.write("<ul>\n")
        for item in data["bullets"]:
            fd.write("  <li>%s</li>\n" % fmt_text(item))
        fd.write("</ul>\n")
    fd.write("</div>\n")

    # Emit additional data with semantics
    if obj.e_typ.name == "Terminal":
        fd.write("<div class='code'>")
        fd.write("<code>%s</code>\n" % data["def"])
        fd.write("</div>\n")
    elif obj.e_typ.name == "Grammar":
        fd.write("<div class='code'>")
        fd.write("<pre>\n")
        first = True
        for production in bnf_parser.bundles[obj.name]:
            if first:
                first = False
            else:
                fd.write("\n")
            write_production(fd, production, bnf_parser)
        fd.write("</pre>\n")
        fd.write("</div>\n")


def write_production(fd, production, bnf_parser):
    # Write indicator with anchor
    fd.write("<a name=\"bnf-%s\"></a>%s ::= " %
             (production, production))
    n_exp = bnf_parser.productions[production]

    if isinstance(n_exp, BNF_Alternatives):
        alt_offset = len(production) + 3
        write_expansion(fd, n_exp.members[0])
        fd.write("\n")
        for n_member in n_exp.members[1:]:
            fd.write(" " * alt_offset + "| ")
            write_expansion(fd, n_member)
            fd.write("\n")

    else:
        write_expansion(fd, n_exp)
        fd.write("\n")


def write_expansion(fd, n_exp):
    if isinstance(n_exp, BNF_Alternatives):
        first = True
        for n_member in n_exp.members:
            if first:
                first = False
            else:
                fd.write(" | ")
            write_expansion(fd, n_member)

    elif isinstance(n_exp, BNF_String):
        first = True
        for n_member in n_exp.members:
            if first:
                first = False
            else:
                fd.write(" ")
            write_expansion(fd, n_member)

    elif isinstance(n_exp, BNF_Optional):
        fd.write("[ ")
        write_expansion(fd, n_exp.expansion)
        fd.write(" ]")

    elif isinstance(n_exp, BNF_One_Or_More):
        fd.write("{ ")
        write_expansion(fd, n_exp.expansion)
        fd.write(" }")

    else:
        assert isinstance(n_exp, BNF_Literal)

        if n_exp.kind == "SYMBOL":
            fd.write("'")
            fd.write(n_exp.value)
            fd.write("'")

        elif n_exp.kind == "TERMINAL":
            fd.write(n_exp.value)
            if n_exp.name:
                fd.write("<i>_%s</i>" % n_exp.name)

        else:
            assert n_exp.kind == "NONTERMINAL"
            fd.write("<a href=\"#bnf-%s\">" % n_exp.value)
            fd.write(n_exp.value)
            fd.write("</a>")
            if n_exp.name:
                fd.write("<i>_%s</i>" % n_exp.name)


def main():
    mh = Message_Handler()
    sm = Source_Manager(mh)

    sm.register_directory("language-reference-manual")
    symbols = sm.process()
    if symbols is None:
        sys.exit(1)

    pkg_lrm = symbols.lookup_assuming(mh, "LRM", ast.Package)
    obj_license = pkg_lrm.symbols.lookup_assuming(mh,
                                                  "License",
                                                  ast.Record_Object)
    typ_text = pkg_lrm.symbols.lookup_assuming(mh, "Text", ast.Record_Type)
    typ_gram = pkg_lrm.symbols.lookup_assuming(mh, "Grammar", ast.Record_Type)
    typ_kword = pkg_lrm.symbols.lookup_assuming(mh, "Keywords", ast.Record_Type)
    typ_punct = pkg_lrm.symbols.lookup_assuming(mh, "Punctuation", ast.Record_Type)

    # Process grammer
    parser = BNF_Parser(mh)
    for obj in pkg_lrm.symbols.iter_record_objects():
        if obj.e_typ.is_subclass_of(typ_gram):
            try:
                parser.parse(obj)
            except TRLC_Error:
                return
        elif obj.e_typ.is_subclass_of(typ_kword):
            for kwobj in obj.field["bullets"].value:
                try:
                    parser.register_terminal(kwobj)
                except TRLC_Error:
                    return
        elif obj.e_typ.is_subclass_of(typ_punct):
            for kwobj in obj.field["bullets"].value:
                try:
                    parser.register_backtick_terminals(kwobj)
                except TRLC_Error:
                    return
    try:
        parser.sem()
    except TRLC_Error:
        return

    context = {
        "old_section": None
    }
    with open("docs/lrm.html", "w", encoding="UTF-8") as fd:
        write_header(fd, obj_license)
        for obj in pkg_lrm.symbols.iter_record_objects():
            if obj.e_typ.is_subclass_of(typ_text):
                write_text_object(fd, obj, context, parser)
        write_footer(fd, os.path.relpath(__file__))


if __name__ == "__main__":
    main()
