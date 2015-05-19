# OTMql4AMQP

### OTMql4AMQP - AMQP bindings for MQL4 Python
https://github.com/OpenTrading/OTMql4OTMql4AMQP/

This project allows the OpenTrading Metatrader-Python bridge
(https://github.com/OpenTrading/OTMql4Py/)
to work with RabbitMQ, or probably any version of AMQP,
the emerging standard for high performance enterprise messaging,
for asynchronous communications between financial and trading applications.
It builds on OTMql4Py, and requires it as a pre-requisite.

In your Python, you must have installed Pika:
https://pypi.python.org/pypi/pika/
Pika offers the advantage of being pure Python: no DLLs to compile
or install. Pika communicates with AMQP servers, the most common
open-source one being RabbitMQ http://www.rabbitmq.com
You will need an AMPQ server installed, configured and running
to use this project. The code assumes the default server setup
of username: guest, password: guest, virtual host: /.

**This is a work in progress - a developers' pre-release version.**

It works on builds > 6xx, but the documentation of the wiring up
of an asnychronous event loop under Python still needs to be done,
as well as more tests and testing on different versions.
Only Python 2.7.x is supported.

The project wiki should be open for editing by anyone logged into GitHub:
**Please report any system it works or doesn't work on in the wiki:
include the Metatrader build number, the origin of the metatrader exe,
the Windows version, and the AMQP server version and version of the Pika.**
This code in known to run under Linux Wine (1.7.x), so this project
bridges Metatrader to RabbitMQ under Linux.

### Installation

For the moment there is no installer: just "git clone" or download the
zip from github.com and unzip into an empty directory. Then recursively copy
the folder MQL4 over the MQL4 folder of your Metatrader installation. It will
not overwrite any Mt4 system files; if it overwrites any OTMql4Py files,
the files are in fact identical (e.g. __init__.py).

### Project

Please file any bugs in the issue tracker:
https://github.com/OpenTrading/OTMql4OTMql4AMQP/issues

Use the Wiki to start topics for discussion:
https://github.com/OpenTrading/OTMql4OTMql4AMQP/wiki
It's better to use the wiki for knowledge capture, and then we can pull
the important pages back into the documentation in the share/doc directory.
You will need to be signed into github.com to see or edit in the wiki.

### Testing

If you open a command window and go to your `MQL4\Python` directory
run this command first
`
python OTMql427/PikaListener.py "#"
`
Then open another command window and go to your `MQL4\Python` directory
run this command second
`
python OTMql427/PikaChart.py "foo"
`
You should soon see `['foo']` appear in the first window.

If it does not work, then solve this problem first, because it
won't work from Python under Mt4 if it doesn't work here.

If you leave the first command running, you should see the tick
and bar information broadcast by the calls in `OnTimer` and `OnTick` in
`MQL4/Experts/OTMql4/OTPyTestPikaEA.mq4`

`OnTimer` is called every iTIMER_INTERVAL_SEC (10 sec.)
which allows us to use Python to look for Pika inbound messages,
or execute a stack of calls from Python to us in Metatrader.
### Round Tripping

Mt4 can call Python, but Python can't call Mt4. So we need to
establish a round-trip from Mt4 that looks to see if there is anything
that Python wants it to do.

The way we do this is to make a Queue object from the Python library
`Queue` and push anything Python wants done onto the Queue in Python.
Then put a timer event in your Mt4 expert that fires periodically
(like even 10 seconds), and calls the Python code to pop the work
off the queue.

However, Mt4 does not have an eval command to handle arbitrary strings
to be executed. So we wrote the `zOTLibProcessCmd` in the OTMql4Lib
project (OTLibProcessCmd.mq4)
that approximates what should be Eval in Mt4.

Depending on how you push things onto the queue, you may want to
take the result of `zOTLibProcessCmd` and distribute it via RabbitMQ.

### Test Expert

There is a test expert advisor in
`Experts/OTMql4/OTPyTestPikaEA.mq4`

Then you open a command window and go to your `MQL4\Python` directory
run the following command to see the messages the expert is broadcasting:
`
python OTMql427/PikaListener.py "#"
`
You can select which RabbitMQ messages you want to subscribe to from
one or more of `ticks` `bars` timer` `retval`
to see just ticks, do
`
python OTMql427/PikaListener.py "tick.#"
`
To see timer events and ticks, do
`
python OTMql427/PikaListener.py "tick.#" "timer.#"
`
Read the RabbitMQ document for further details of using `#` and `*`
to select the messages you are interested in; you can select by
type of message, the currency pair, period, the hex value of the `ChartID`.

The interval for timer events can be set when you attach the expert:
`
extern int iTIMER_INTERVAL_SEC = 10;
`

The information that is put on a tick is supplied by the function
`sBarInfo` which puts together the information you want send
to a remote client on every bar. Change it to suit your own needs:
`
#include <OTMql4/OTBarInfo.mqh>
`

You can have many experts running on many charts. There is only one
`Pika.connection.Connection` object, and it is shared by all charts.
The total number of charts using the connection is kept in the global variable
`fPY_PIKA_CONNECTION_USERS`. When the last expert is removed, this
number drops to 0, and the Connection is shut down.

You should always remove any `OTMql4Py` experts before you shut down Mt4.
It may not initialize properly if you start Mt4 with an `OTMql4Py`
expert already attached. You may have to remove the expert and restart
Mt4 if it does not initialize properly.

Specifically, if you load an `OTMql4Py` expert and the Mt4 log shows
a message about `exceptions.SystemError`, it means that the Python
DLL did not load properly, and you *must* restart if you want to use
an `OTMql4Py` expert. You should get a pop-up Alert from Mt4 to alert
you of this.

## PikaCmd2.py

This script can be run from the command line to send commands
to a OTMql4Pika enabled Metatrader. It will start a command loop to
listen, send commands, or query the RabbitMQ management interface, based 
on the cmd2 REPL: see cmd2plus.py in https://github.com/OpenTrading/OTMql4Lib

Type help at the command prompt to get more help.

Call the script with --help to see the script options.

The normal usage is:

sub topics timer.# retval.# - to subscribe to a message queue of events
sub run                     - to start a thread listening for messages
pub cmd AccountBalance      - to send a command to OTMql4Pika,
                              the return will be a retval message on the listener

### chart

Set and query the chart used for messages to and from RabbitMQ:
  list   - all the charts the listener has heard of,
           iff you have already started a listener with "sub run"
  get    - get the default chart to be published or subscribed to.
  set ID - set the default chart ID to be published or subscribed to.
  set    - set the default chart to be the last chart the listener has heard of,
           iff you have already started a listener with "sub run"
  add    - NOTImplemented
  remove - NOTImplemented

The chart ID will look something like: oChart_EURGBP_240_93ACD6A2_1

### sub
Subscribe to messages from RabbitMQ on a given topic:
  sub topics TOPIC1 ... - subscribes to topics.
  sub show              - shows topics subscribed to.
  sub run               - start a thread to listen for messages.
  sub stop              - start a thread to listen for messages.
  sub clear             - clear the list of subscribed topics NOTImplemented.

Common topics are: # for all messages, tick.# for ticks,
timer.# for timer events, retval.# for return values.
You can choose as specific chart with syntax like:
    tick.oChart.EURGBP.240.93ACD6A2.#

### pub
Publish a message via RabbitMQ to a given chart on a OTMql4Py enabled terminal:
  pub cmd  COMMAND|ARG1|... - publish a Mql command to Mt4,
      the command should be a single string, with | seperating from arguments.
  pub eval COMMAND|ARG1|... - publish a Python command to the OTMql4Py,
      the command should be a single string, with | seperating from arguments.

### rabbit
If we have pyrabbit installed, and iff the rabbitmq_management plugin
has been installed in your server, we can introspect some useful
information if the HTTP interface is enabled. Commands include:
    get vhost_names
    get channels
    get connections
    get queues

### Messaging Format

The messaging to and from OTMql4Py is still being done with a
very simple format:
      sMsgType|sChartId|sIgnored|sMark|sPayload
where sMsgType is one of: cmd eval (outgoing), timer tick retval (incoming);
      sChartId is the Mt4 chart sChartId the message is to or from;
      sMark is a simple floating point timestamp, with milliseconds;
and   sPayload is command|arg1|arg2... (outgoing) or type|value (incoming),
      where type is one of: bool int double string json.
This breaks if the sPayload args or value contain a | -
we will probably replace this with json or pickled serialization, or kombu.
