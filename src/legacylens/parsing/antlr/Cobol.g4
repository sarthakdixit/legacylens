/*
 * Cobol.g4 — starter "island" grammar for legacylens structural extraction.
 *
 * This is NOT a full COBOL grammar. It recognizes only the constructs legacylens
 * needs (PROGRAM-ID, divisions, paragraphs, CALL, COPY, data-item levels) and skips
 * everything else via the `anyToken` fallback. It parses the CLEANED, UPPER-CASED
 * code emitted by AntlrCobolParser._preprocess (no sequence area, no comments).
 *
 * The key advantage over regex: the STRING lexer rule absorbs literal contents, so
 * `DISPLAY 'GU CALL TO ROOT'` never yields a phantom CALL, and hyphenated names like
 * INSERT-IMS-CALL are single NAME tokens (no false CALL suffix match).
 *
 * Clients wanting fuller fidelity can extend this or drop in a mature grammar such
 * as ProLeap's COBOL85 grammar; the listener in backend.py keys off the rule names
 * below (programId, division/divisionName, copyStmt, callStmt, paragraph,
 * dataDescription) — keep those stable or update the listener accordingly.
 *
 * Generate with:  python scripts/build_antlr.py
 */
grammar Cobol;

program         : element* EOF ;

element         : programId
                | division
                | copyStmt
                | callStmt
                | dataDescription
                | paragraph
                | anyToken ;

programId       : PROGRAM_ID DOT? NAME DOT? ;
division        : divisionName DIVISION DOT? ;
divisionName    : IDENTIFICATION | ENVIRONMENT | DATA | PROCEDURE | NAME ;
copyStmt        : COPY NAME ;
callStmt        : CALL ( STRING | NAME ) ;
dataDescription : LEVEL NAME ;
paragraph       : NAME DOT ;
anyToken        : . ;

// ------- Lexer (upper-case; input is upper-cased before lexing) -------
PROGRAM_ID     : 'PROGRAM-ID' ;
IDENTIFICATION : 'IDENTIFICATION' ;
ENVIRONMENT    : 'ENVIRONMENT' ;
DATA           : 'DATA' ;
PROCEDURE      : 'PROCEDURE' ;
DIVISION       : 'DIVISION' ;
COPY           : 'COPY' ;
CALL           : 'CALL' ;
LEVEL          : [0-9][0-9]? ;
NAME           : [A-Z0-9] [A-Z0-9-]* ;
STRING         : '\'' ~['\r\n]* '\'' | '"' ~["\r\n]* '"' ;
DOT            : '.' ;
WS             : [ \t\r\n]+ -> skip ;
ANY            : . ;
