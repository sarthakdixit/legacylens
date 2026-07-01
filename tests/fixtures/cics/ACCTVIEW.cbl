       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTVIEW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM-NAME   PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS LINK PROGRAM('INQCUST')
                     COMMAREA(WS-COMMAREA)
           END-EXEC.
           EXEC CICS XCTL PROGRAM(WS-PGM-NAME)
           END-EXEC.
           EXEC SQL
               SELECT ACCT_BAL INTO :WS-BAL
               FROM   ACCTDB.ACCOUNTS
               WHERE  ACCT_ID = :WS-ID
           END-EXEC.
           EXEC SQL
               UPDATE ACCTDB.ACCOUNTS SET ACCT_BAL = :WS-BAL
           END-EXEC.
           GOBACK.
