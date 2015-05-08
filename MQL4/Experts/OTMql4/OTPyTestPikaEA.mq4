// -*-mode: c; c-style: stroustrup; c-basic-offset: 4; coding: utf-8-dos -*-

#property copyright "Copyright 2015 OpenTrading"
#property link      "https://github.com/OpenTrading/"
#property strict

#define INDICATOR_NAME          "PyTestPikaEA"

//? extern int iSEND_PORT=5672;
//? extern int iRECV_PORT=5672;
// can replace this with the IP address of an interface - not lo
extern string uHOST_ADDRESS="127.0.0.1";
extern string uUSERNAME = "guest";
extern string uPASSWORD = "guest";
extern string uEXCHANGE_NAME = "Mt4";
// for testing - in real life we probably want "Mt4" in here for permissions
extern string uVIRTUALHOST = "/";
extern int iTIMER_INTERVAL_SEC = 10;

// disabled if = 0 - callme is not working even though it should be. YMMV.
int iCALLME_TIMEOUT = 0;

extern string uStdOutFile="../../Logs/_test_PyTestPikaEA.txt";

#include <WinUser32.mqh>
/*
This provides the function sBarInfo which puts together the
information you want send to a remote client on every bar.
Change to suit your own needs.
*/
#include <OTMql4/OTBarInfo.mqh>

#include <OTMql4/OTLibLog.mqh>
#include <OTMql4/OTLibStrings.mqh>
#include <OTMql4/OTLibMt4ProcessCmd.mqh>
#include <OTMql4/OTLibProcessCmd.mqh>
#include <OTMql4/OTLibSimpleFormatCmd.mqh>
#include <OTMql4/OTLibPy27.mqh>
//unused #include <OTMql4/OTPyPika.mqh>

int iCONNECTION = -1;
double fPY_PIKA_CONNECTION_USERS = 0.0;

string uSYMBOL;
int iTIMEFRAME;
int iACCNUM;

int iTICK=0;
int iBAR=1;

string uOTPyPikaProcessCmd(string uCmd) {
    string uRetval;
    uRetval = zOTLibProcessCmd(uCmd);
    // can be "void|" return value
    // empty string means the command was not handled.
    return(uRetval);
}

void vPanic(string uReason) {
    // A panic prints an error message and then aborts
    vError("PANIC: " + uReason);
    MessageBox(uReason, "PANIC!", MB_OK|MB_ICONEXCLAMATION);
    ExpertRemove();
}

int iIsEA=1;
double fDebugLevel=0;

string uSafeString(string uSymbol) {
    uSymbol = uStringReplace(uSymbol, "!", "");
    uSymbol = uStringReplace(uSymbol, "#", "");
    uSymbol = uStringReplace(uSymbol, "-", "");
    uSymbol = uStringReplace(uSymbol, ".", "");
    return(uSymbol);
}
string uCHART_ID = uChartName(uSafeString(Symbol()), Period(), ChartID(), iIsEA);


int OnInit() {
    int iRetval;
    string uExchangeName;
    string uArg, uRetval;

    if (GlobalVariableCheck("fPyPikaConnectionUsers") == true) {
        fPY_PIKA_CONNECTION_USERS=GlobalVariableGet("fPyPikaConnectionUsers");
    } else {
        fPY_PIKA_CONNECTION_USERS = 0.0;
    }
    if (fPY_PIKA_CONNECTION_USERS > 0.1) {
	iCONNECTION = MathRound(GlobalVariableGet("fPyPikaConnection"));
	if (iCONNECTION < 1) {
	    vError("OnInit: unallocated connection");
	    return(-1);
	}
        fPY_PIKA_CONNECTION_USERS += 1.0;
    } else {
	iRetval = iPyInit(uStdOutFile);
	if (iRetval != 0) {
	    return(iRetval);
	}
	Print("Called iPyInit successfully");
	
	uSYMBOL=Symbol();
	iTIMEFRAME=Period();
	iACCNUM=AccountNumber();

	uArg="import pika";
	vPyExecuteUnicode(uArg);
	// VERY IMPORTANT: if the import failed we MUST PANIC
	vPyExecuteUnicode("sFoobar = '%s : %s' % (sys.last_type, sys.last_value,)");
	uRetval=uPyEvalUnicode("sFoobar");
	if (StringFind(uRetval, "exceptions.SystemError", 0) >= 0) {
	    // Were seeing this during testing after an uninit 2 reload
	    uRetval = "PANIC: import pika failed - we MUST restart Mt4:"  + uRetval;
	    vPanic(uRetval);
	    return(-2);
	}
	if (StringFind(uRetval, "Error", 0) >= 0) {
	    uRetval = "PANIC: import pika failed:"  + uRetval;
	    vPanic(uRetval);
	    return(-2);
	}
	vPyExecuteUnicode("from OTMql427 import PikaChart");
	vPyExecuteUnicode("sFoobar = '%s : %s' % (sys.last_type, sys.last_value,)");
	uRetval = uPySafeEval("sFoobar");
	if (StringFind(uRetval, "exceptions", 0) >= 0) {
	    uRetval = "ERROR: import PikaChart failed: "  + uRetval;
	    vPanic(uRetval);
	    return(-3);
	} else {
	    uRetval = "import PikaChart succeeded: "  + uRetval;
	    vDebug(uRetval);
	}

	// for testing - in real life we probably want the PID in here
	uExchangeName = uEXCHANGE_NAME;
	vPyExecuteUnicode(uCHART_ID+"=PikaChart.PikaChart(" +
			  "'" +uCHART_ID + "', " +
			  "sUsername='" + uUSERNAME + "', " +
			  "sPassword='" + uPASSWORD + "', " +
			  "sExchangeName='" + uExchangeName + "', " +
			  "sVirtualHost='" + uVIRTUALHOST + "', " +
			  "sHostAddress='" + uHOST_ADDRESS + "', " +
			  "iDebugLevel=" + MathRound(fDebugLevel) + ", " +
			  ")");
	vPyExecuteUnicode("sFoobar = '%s : %s' % (sys.last_type, sys.last_value,)");
	uRetval = uPySafeEval("sFoobar");
	if (StringFind(uRetval, "exceptions", 0) >= 0) {
	    uRetval = "ERROR: PikaChart.PikaChart failed: "  + uRetval;
	    vPanic(uRetval);
	    return(-3);
	} else if (uRetval != " : ") {
	    uRetval = "PikaChart.PikaChart errored: "  + uRetval;
	    vWarn(uRetval);
	}
	
	iCONNECTION = iPyEvalInt("id(" +uCHART_ID +".oCreateConnection())");
	// FixMe:! theres no way to no if this errored! No NAN in Mt4
	if (iCONNECTION <= 0) {
	    uRetval = "ERROR: oCreateConnection failed: is RabbitMQ running?";
	    vPanic(uRetval);
	    return(-3);
	} else {
	    uRetval = "oCreateConnection() succeeded: "  + iCONNECTION;
	    vInfo(uRetval);
	}
	GlobalVariableTemp("fPyPikaConnection");
	GlobalVariableSet("fPyPikaConnection", iCONNECTION);

	if (iCALLME_TIMEOUT > 0) {
	    vInfo("INFO: starting CallmeServer - this make take a while");
	    uRetval = uPySafeEval(uCHART_ID+".eStartCallmeServer()");
	    if (StringFind(uRetval, "ERROR:", 0) >= 0) {
		uRetval = "WARN: zStartCallmeServer failed: "  + uRetval;
		vWarn(uRetval);
	    } else if (uRetval == "") {
		vInfo("INFO: zStartCallmeServer succeeded");
	    } else {
		uRetval = "WARN: eStartCallmeServer returned"  + uRetval;
		vWarn(uRetval);
	    }
	}
	
        fPY_PIKA_CONNECTION_USERS = 1.0;
	
    }
    GlobalVariableSet("fPyPikaConnectionUsers", fPY_PIKA_CONNECTION_USERS);
    vDebug("OnInit: fPyPikaConnectionUsers=" + fPY_PIKA_CONNECTION_USERS);

    EventSetTimer(iTIMER_INTERVAL_SEC);
    return (0);
}

/*
OnTimer is called every iTIMER_INTERVAL_SEC (10 sec.)
which allows us to use Python to look for Pika inbound messages,
or execute a stack of calls from Python to us in Metatrader.
*/
void OnTimer() {
    string uRetval="";
    string uMessage;
    string uMess, uInfo;
    string uType = "timer";
    string uMark;

    uCHART_ID = uChartName(uSafeString(Symbol()), Period(), ChartID(), iIsEA);
    /* timer events can be called before we are ready */
    if (GlobalVariableCheck("fPyPikaConnectionUsers") == false) {
      return;
    }
    iCONNECTION = MathRound(GlobalVariableGet("fPyPikaConnection"));
    if (iCONNECTION < 1) {
	vWarn("OnTimer: unallocated connection");
        return;
    }

    // FixMe: could use GetTickCount but we may not be logged in
    // but maybe TimeCurrent requires us to be logged in?
    string uTime = IntegerToString(TimeCurrent());
    
    uInfo = "0";
    uRetval = uPySafeEval(uCHART_ID+".eHeartBeat("
			  +IntegerToString(iCALLME_TIMEOUT) +")");
    if (StringFind(uRetval, "ERROR: ", 0) >= 0) {
	uRetval = "ERROR: eHeartBeat failed: "  + uRetval;
	vWarn("OnTimer: " +uRetval);
	return;
    }
    // There may be sleeps for threads here
    // We may want to loop over zMq4PopQueue to pop many commands
    uRetval = uPySafeEval(uCHART_ID+".zMq4PopQueue()");
    if (StringFind(uRetval, "ERROR:", 0) >= 0) {
	uRetval = "ERROR: zMq4PopQueue failed: "  + uRetval;
	vWarn("OnTimer: " +uRetval);
	return;
    }

    // the uRetval will be empty if there is nothing to do.
    if (uRetval == "") {
	//vTrace("OnTimer: " +uRetval);
    } else {
	//vTrace("OnTimer: Processing popped exec message: " + uRetval);
	uMess = uOTPyPikaProcessCmd(uRetval);
	if (uMess == "void|") {
	    // can be "void|" return value
	} else if (StringFind(uRetval, "cmd", 0) == 0) {
	    // if the command is cmd|  - return a value as a retval|
	    // We want the sMark from uRetval instead of uTime
	    // but we will do than in Python
	    uMark = "0";
	    uMess  = zOTLibSimpleFormatRetval("retval", uCHART_ID, 0, uMark, uMess);
	    eSendOnSpeaker("retval", uMess, uRetval);
	    vDebug("OnTimer: retvaled " +uMess);
	} else {
	    // if the command is exec| - dont return a value
	    vDebug("OnTimer: processed " +uMess);
	}
    }
    
    uMess  = zOTLibSimpleFormatTick(uType, uCHART_ID, 0, uTime, uInfo);
    eSendOnSpeaker("timer", uMess);
}

void OnTick() {
    static datetime tNextbartime;
    bool bNewBar=false;
    string uType;
    string uInfo;
    string uMess, uRetval;

    uCHART_ID = uChartName(uSafeString(Symbol()), Period(), ChartID(), iIsEA);
   fPY_PIKA_CONNECTION_USERS=GlobalVariableGet("fPyPikaConnectionUsers");
    if (fPY_PIKA_CONNECTION_USERS < 0.5) {
	vWarn("OnTick: no connection users");
        return;
    }
    iCONNECTION = MathRound(GlobalVariableGet("fPyPikaConnection"));
    if (iCONNECTION < 1) {
	vWarn("OnTick: unallocated connection");
        return;
    }

    // FixMe: could use GetTickCount but we may not be logged in
    // but maybe TimeCurrent requires us to be logged in?
    string uTime = IntegerToString(TimeCurrent());
    // same as Time[0]
    datetime tTime=iTime(uSYMBOL, iTIMEFRAME, 0);

    if (tTime != tNextbartime) {
        iBAR += 1; // = Bars - 100
	bNewBar = true;
	iTICK = 0;
	tNextbartime = tTime;
	uInfo = sBarInfo();
	uType = "bar";
    } else {
        bNewBar = false;
	iTICK += 1;
	uInfo = iTICK;
	uType = "tick";
    }

    uMess  = zOTLibSimpleFormatTick(uType, uCHART_ID, 0, uTime, uInfo);
    eSendOnSpeaker(uType, uMess);
}

void eSendOnSpeaker(string uType, string uMess, string uOriginCmd="") {
    string uRetval;
    if (uOriginCmd == "") {
	uMess = uCHART_ID +".eSendOnSpeaker('" +uType +"', '" +uMess +"')";
    } else {
	// This message is a reply in a cmd
	uMess = uCHART_ID +".eSendOnSpeaker('" +uType +"', '" +uMess
	    +"', '" +uOriginCmd +"')";
    }
    //vTrace("eSendOnSpeaker:  uMess: " +uMess);
    // the retval should be empty - otherwise its an error
    vPyExecuteUnicode(uMess);
    vPyExecuteUnicode("sFoobar = '%s : %s' % (sys.last_type, sys.last_value,)");
    uRetval=uPyEvalUnicode("sFoobar");
    if (StringFind(uRetval, "exceptions", 0) >= 0) {
	vWarn("eSendOnSpeaker: ERROR: " +uRetval);
	return;
    } else if (uRetval != " : ") {
	vDebug("eSendOnSpeaker:  WTF?" +uMess);
    } else {
	// pass
    }
}

void OnDeinit(const int iReason) {
    //? if (iReason == INIT_FAILED) { return ; }
    EventKillTimer();

    fPY_PIKA_CONNECTION_USERS=GlobalVariableGet("fPyPikaConnectionUsers");
    if (fPY_PIKA_CONNECTION_USERS < 1.5) {
	iCONNECTION = MathRound(GlobalVariableGet("fPyPikaConnection"));
	if (iCONNECTION < 1) {
	    vWarn("OnDeinit: unallocated connection");
	} else {
	    vInfo("OnDeinit: closing the connection");
	    vPyExecuteUnicode(uCHART_ID +".bCloseConnectionSockets()");
	}
	GlobalVariableDel("fPyPikaConnection");

	GlobalVariableDel("fPyPikaConnectionUsers");
	vDebug("OnDeinit: deleted fPyPikaConnectionUsers");
	
	vPyDeInit();
    } else {
	fPY_PIKA_CONNECTION_USERS -= 1.0;
	GlobalVariableSet("fPyPikaConnectionUsers", fPY_PIKA_CONNECTION_USERS);
	vDebug("OnDeinit: decreased, value of fPyPikaConnectionUsers to: " + fPY_PIKA_CONNECTION_USERS);
    }
    
    vDebug("OnDeinit: delete of the chart in Python");
    vPyExecuteUnicode(uCHART_ID +".vRemove()");

}
