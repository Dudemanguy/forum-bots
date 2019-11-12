import getpass
import http.cookiejar
import mechanize
import random
import re
import socket
import ssl
import time
from bs4 import BeautifulSoup

def channel_join(state, irc, channel):
    time.sleep(1)
    irc.send(bytes("JOIN " + channel + "\n", "UTF-8"))
    state["in_channel"] = True

def check_for_command(state, irc, channel, text):
    if text.find(".jmfbot ") != -1:
        raw = text.split("#jpmetal ")[1][1:]
        str_split = raw.split(None, 2)
        if str_split[0] == ".jmfbot" and len(str_split) > 1:
            user = text.split("~")[0][1:]
            user = user[:len(user)-1]
            execute_command(state, irc, channel, str_split[1:], user)

def check_for_ragequit(state, irc, channel, text):
    if len(text.split(":")) == 3:
        subset = text.split(":")[1]
        if subset.find("QUIT") != -1 and subset[:8] == "Jeckidy!":
            state["ragequits"] += 1
            msg_send(irc, channel, "Ragequit counter updated to "+str(state["ragequits"]))

def check_for_user_entry(state, irc, channel, text):
    if len(text.split(":")) == 3:
        subset = text.split(":")[1]
        if subset.find("JOIN") != -1:
            user = subset.split("!")[0]
            msg_send(irc, channel, "hi "+user)

def execute_command(state, irc, channel, str_split, user):
    command = str_split[0]
    arguments = ""
    if len(str_split) > 1:
        arguments = str_split[1]
    if command == "echo" and arguments != "":
        msg_send(irc, channel, arguments)
    elif command == "help" and arguments == "":
        msg_send(irc, channel, "Usage: .jmfbot [command] [arguments]")
        time.sleep(1)
        msg_send(irc, channel, "Type '.jmfbot help [command]' for more details about a particular command")
        time.sleep(1)
        msg_send(irc, channel, "Available commands: echo, help, kill, list, random, set, show")
    elif command == "help" and arguments != "":
        if arguments == "echo":
            msg_send(irc, channel, "echo [message] -- tell the bot echo back a message")
        if arguments == "help":
            msg_send(irc, channel, "help [command (optional)] -- display detailed help output for a particular command")
        if arguments == "kill":
            msg_send(irc, channel, "kill [timeout (optional)] -- kill the bot with an optional timeout (channel op only)")
        if arguments == "list":
            msg_send(irc, channel, "list [actions|properties] -- list all actions/properties with a short description")
        if arguments == "random":
            msg_send(irc, channel, "random [action] -- randomize a certain action")
        if arguments == "reboot":
            msg_send(irc, channel, "reboot [timeout (optional)] -- reboot the bot with an optional timeout (channel op only)")
        if arguments == "set":
            msg_send(irc, channel, "set [property] [value] -- set one of the bot's properties to a particular value (channel op only)")
        if arguments == "show":
            msg_send(irc, channel, "show [property] -- show the value of one of the bot's properties")
    elif command == "kill":
        if is_op(irc, channel, user):
            if arguments != "" and only_numbers(arguments):
                state["timestamp"] = time.time()
                state["timeout"] = int(arguments)
                msg_send(irc, channel, "Killing bot in "+arguments+" seconds")
            elif arguments != "" and not only_numbers(arguments):
                msg_send(irc, channel, "Error: the timeout must be an integer value")
                return
            state["kill"] = True
        else:
            msg_send(irc, channel, "Only channel ops can kill me.")
    elif command == "list" and arguments != "":
        if arguments == "actions":
            msg_send(irc, channel, "thread -- retrieve a thread from the forum")
        elif arguments == "properties":
            msg_send(irc, channel, "greeter -- greet users on entry (boolean: on/off)")
            time.sleep(1)
            msg_send(irc, channel, "ragequits -- ragequit counter (integer)")
    elif command == "reboot":
        if is_op(irc, channel, user):
            if arguments != "" and only_numbers(arguments):
                state["timestamp"] = time.time()
                state["timeout"] = int(arguments)
                msg_send(irc, channel, "Rebooting bot in "+arguments+" seconds")
            elif arguments != "" and not only_numbers(arguments):
                msg_send(irc, channel, "Error: the reboot time must be an integer value")
                return
            state["reboot"] = True
        else:
            msg_send(irc, channel, "Only channel ops can reboot me.")
    elif command == "random" and arguments != "":
        if arguments == "thread":
            # add a random constant that exists for unknown reasons but whatever
            thread_count = get_thread_count() + 803
            rand_soup = -1
            while rand_soup == -1:
                time.sleep(1)
                rand_tid = random.randint(1, thread_count)
                rand_url = baseurl+str(rand_tid)
                rand_soup = get_html(rand_url)
            thread_title = rand_soup.find("title").contents[0]
            msg_send(irc, channel, "Random thread: "+thread_title+" -- "+rand_url)
    elif command == "set" and arguments != "":
        if not is_op(irc, channel, user):
            msg_send(irc, channel, "Only channel ops can use the set command.")
        arguments = arguments.split()
        if arguments[0] == "greeter":
            if arguments[1] == "on":
                state["greeter"] = True
                msg_send(irc, channel, "User greeter turned on")
            elif arguments[1] == "off":
                state["greeter"] = False
                msg_send(irc, channel, "User greeter turned off")
        elif arguments[0] == "ragequits":
            if only_numbers(arguments[1]):
                state["ragequits"] = int(arguments[1])
                msg_send(irc, channel, "Ragequit counter updated to "+str(state["ragequits"]))
            else:
                msg_send(irc, channel, "Error: ragequits can only be set to an integer value")
    elif command == "show" and arguments != "":
        if arguments == "ragequits":
            msg_send(irc, channel, "The ragequit counter is at "+str(state["ragequits"]))

def exists_in_old(item, old_full):
    for i in range(0, len(old_full)):
        if item == old_full[i]:
            return True
    return False

def get_html(url):
    try:
        html = br.open(url).read()
        soup = BeautifulSoup(html, "html.parser")
        return soup
    except:
        return -1

def get_response(irc):
    resp = irc.recv(4096).decode("UTF-8").rstrip("\r\n")
    return resp

def get_thread_count():
    soup = get_html(statsurl)
    return int(soup.find_all("td")[3].find_all("strong")[1].contents[0].replace(",",""))

def identify_name(state, irc, text, botpass):
    if text.find('PING') != -1:
        irc.send(bytes("PRIVMSG NickServ@services.rizon.net :IDENTIFY "+botpass+"\r\n", "UTF-8"))
        state["identified"] = True

def is_op(irc, channel, user):
    irc.send(bytes("NAMES " + channel + "\n", "UTF-8"))
    names = get_response(irc)
    names = names.split()
    for i in names:
        if i[0] == "@" and user == i[1:]:
            return True
    return False

def msg_send(irc, channel, msg):
    irc.send(bytes("PRIVMSG " + channel + " :" + msg + "\n", "UTF-8"))

def only_numbers(string):
    for i in string:
        if not i.isdigit():
            return False
    return True

def reply_pong(irc, text):
    if text.find('PING') != -1:                      
        for i in range(len(text.split())):
            if text.split()[i] == "PING":
                irc.send(bytes('PONG '+text.split()[i+1]+'\r\n', "UTF-8"))

def server_connect(irc, server, port, botnick):
    print("Connecting to: " + server)
    irc.connect((server, port))
    irc.send(bytes("USER " + botnick + " " + botnick +" " + botnick + " :python\n", "UTF-8"))
    irc.send(bytes("NICK " + botnick + "\n", "UTF-8"))
    time.sleep(5)

def update_info(soup):
    poster = []
    thread = []
    time = []
    url = []
    poster_names = soup.find_all("span", class_="smalltext")
    thread_names = soup.find_all("a", {"id" : re.compile("tid_.*")})
    for i in range(len(poster_names)-1, -1, -1):
        if poster_names[i].strong != None and poster_names[i].span != None:
            if str(poster_names[i].a).find("search") > -1:
                continue
            poster.append(poster_names[i].strong.contents[0])
    for i in range(len(thread_names)-1, -1, -1):
        thread.append(thread_names[i].contents[0])
    for i in range(len(poster_names)-1, -1, -1):
        if poster_names[i].span != None and str(poster_names[i].a).find("search") == -1:
            time.append(poster_names[i].contents[2][2:])
    for i in range(len(thread_names)-1, -1, -1):
        thread_id = thread_names[i].get('id')[4:]
        url.append(baseurl+thread_id+"&action=lastpost")
    full = []
    for i in range(len(poster)):
        full.append([poster[i], thread[i], time[i], url[i]])
    return full

baseurl = "https://jpmetal.org/showthread.php?tid="
loginurl = "https://jpmetal.org/member.php?action=login"
searchurl = "https://jpmetal.org/search.php?action=getdaily"
statsurl = "https://jpmetal.org/stats.php"
cj = http.cookiejar.CookieJar()

br = mechanize.Browser()
br.set_cookiejar(cj)
br.set_handle_equiv(True)
br.set_handle_gzip(True)
br.set_handle_redirect(True)
br.set_handle_referer(True)
br.set_handle_robots(False)
br.set_handle_refresh(mechanize._http.HTTPRefreshProcessor(), max_time=1)
br.addheaders = [('User-agent', 'Mozilla/5.0 (Windows NT 10.0; rv:68.0) Gecko/20100101 Firefox/68.0')]

br.open(loginurl)
br.select_form(nr=1)
br.form['username'] = input("Username: ")
br.form['password'] = getpass.getpass("Password: ")
botpass = br.form['password']
br.submit()

server = "irc.rizon.net"
port = 6697
channel = "#jpmetal"
botnick = "JMFbot"
irc = socket.socket()
irc = ssl.wrap_socket(irc)

server_connect(irc, server, port, botnick)
state = {
    "connected" : True,
    "first_join" : True,
    "fully_started" : False,
    "greeter" : True,
    "identified" : False,
    "in_channel" : False,
    "kill" : False,
    "ragequits" : 0,
    "reboot" : False,
    "timeout" : 0,
    "timestamp" : 0
}
old_full = []
old_time = 0

while True:
    if not state["connected"]:
        irc = socket.socket()
        irc = ssl.wrap_socket(irc)
        server_connect(irc, server, port, botnick)
        state["connected"] = True

    if state["connected"]:
        text = get_response(irc)
        print(text)

    elapsed_time = time.time() - old_time

    reply_pong(irc, text)

    if not state["fully_started"]:
        if not state["identified"]:
            identify_name(state, irc, text, botpass)

        if text.find('+r') != -1:                      
            channel_join(state, irc, channel)

        if text.find('+v') != -1:
            msg_send(irc, channel, "hi")
            state["fully_started"] = True
        continue

    check_for_command(state, irc, channel, text)
    check_for_ragequit(state, irc, channel, text)

    if state["kill"]:
        if time.time() >= state["timestamp"] + state["timeout"]:
            msg_send(irc, channel, "bbl")
            irc.shutdown(0)
            irc.close()
            break

    if state["reboot"]:
        if time.time() >= state["timestamp"] + state["timeout"]:
            msg_send(irc, channel, "brb")
            irc.shutdown(0)
            irc.close()
            state["connected"] = False
            state["first_join"] = True
            state["fully_started"] = False
            state["identified"] = False
            state["in_channel"] = False
            state["reboot"] = False

    if state["greeter"]:
        check_for_user_entry(state, irc, channel, text)

    if state["fully_started"] and elapsed_time > 60:
        soup = get_html(searchurl)
        full = update_info(soup)
        for i in range(0, len(full)):
            if not exists_in_old(full[i], old_full) and not state["first_join"]:
                msg_send(irc, channel, "[jmfbot] "+full[i][0]+" made a new post in thread: "+full[i][1]+" ("+full[i][2]+") -- "+full[i][3])
                time.sleep(1)
        if state["first_join"]:
            state["first_join"] = False
        old_full = full
        old_time = time.time()

    time.sleep(5)
