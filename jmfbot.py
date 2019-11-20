#!/usr/bin/env python3

import argparse
import getpass
import http.cookiejar
import json
import mechanize
import os
import random
import re
import select
import socket
import ssl
import time
from bs4 import BeautifulSoup

class irc_bot():
    baseurl = "https://jpmetal.org/showthread.php?tid="
    loginurl = "https://jpmetal.org/member.php?action=login"
    searchurl = "https://jpmetal.org/search.php?action=getdaily"
    statsurl = "https://jpmetal.org/stats.php"

    botnick = ""
    botpass = ""
    br = ""
    channel = ""
    names = []
    port = ""
    server = ""
    ssl = ""

    irc = ""
    poller = ""

    state = {
        "greeter" : True,
        "identify" : True,
        "kill" : False,
        "op-only": False,
        "ragequits" : 0,
        "reboot" : False,
        "ssl" : True,
        "timeout" : 0,
        "timestamp" : 0
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--botnick", type=str, default="jmfbot", nargs='?', const=1, help="bot nickname")
    parser.add_argument("--botpass", type=str, default= "", nargs='?', const=1, help="bot password")
    parser.add_argument("--channel", type=str, default="#jpmetal", nargs='?', const=1, help="channel to join")
    parser.add_argument("--identify", type=int, default=1, help="identify name to server")
    parser.add_argument("--server", type=str, default="irc.rizon.net", nargs='?', const=1, help="server to use")
    parser.add_argument("--ssl", type=int, default=1, help="use ssl")
    args = parser.parse_args()

    bot = irc_bot()

    bot.botnick = args.botnick
    bot.botpass = args.botpass
    bot.channel = args.channel
    bot.names.append(bot.botnick)
    bot.server = args.server

    bot.br,bot.botpass = mechanize_login(bot)
    bot.br.submit()
    
    if args.identify == 0:
        bot.state["identify"] = False
    else:
        bot.state["identify"] = True

    if args.ssl == 0:
        bot.state["ssl"] = False
        bot.port = 6667
    else:
        bot.state["ssl"] = True
        bot.port = 6697

    if os.path.isfile("bot_state.txt"):
        with open("bot_state.txt") as f:
            bot.state = json.load(f)

    init = {
        "first_join" : True,
        "fully_started" : False,
        "identified" : False,
    }

    old_full = []
    bot.irc = socket.socket()
    if bot.state["ssl"]:
        bot.irc = ssl.wrap_socket(bot.irc)
    server_connect(bot.irc, bot.server, bot.port, bot.botnick)

    bot.poller = select.poll()
    bot.poller.register(bot.irc, select.POLLIN)

    finish_time = time.time() + 60
    timeout = 60*1000

    bot.irc.setblocking(0)

    while True:
        current_time = time.time()
        if current_time < finish_time:
            timeout = (finish_time - current_time)*1000
        bot.poller.poll(timeout)
        text = get_response(bot.irc)
        if text != "":
            print(text)

        check_text(bot, init, text)

        if not init["fully_started"]:
            if not init["identified"] and bot.state["identify"]:
                if text.find("PING") != -1:
                    identify_name(bot, text)
                    if text.find("Password incorrect.") != -1:
                        bot.botpass = getpass.getpass("Password: ")
                    else:
                        init["identified"] = True

            if init["identified"]:
                get_names(bot, text)
                if text.find('+r') != -1:                      
                    channel_join(bot)
                if text.find('+v') != -1:
                    msg_send(bot.irc, bot.channel, "hi")
                    init["fully_started"] = True
            else:
                get_names(bot, text)
                if text.find("Own a large/active channel") != -1:
                    channel_join(bot)
                if text.find("End of /NAMES list.") != -1:
                    msg_send(bot.irc, bot.channel, "hi")
                    init["fully_started"] = True

        if bot.state["kill"]:
            if time.time() >= bot.state["timestamp"] + bot.state["timeout"]:
                bot.state["kill"] = False
                with open("bot_state.txt", "w") as json_file:
                    json.dump(bot.state, json_file)
                msg_send(bot.irc, bot.channel, "bbl")
                bot.irc.setblocking(1)
                bot.irc.shutdown(0)
                bot.irc.close()
                break

        if bot.state["reboot"]:
            if time.time() >= bot.state["timestamp"] + bot.state["timeout"]:
                bot.state["reboot"] = False
                with open("bot_state.txt", "w") as json_file:
                    json.dump(bot.state, json_file)
                msg_send(bot.irc, bot.channel, "brb")
                bot.irc.setblocking(1)
                bot.irc.shutdown(0)
                bot.irc.close()
                os.execl("jmfbot.py", "--botnick="+bot.botnick, "--botpass="+bot.botpass)

        if init["fully_started"] and time.time() >= finish_time:
            soup = get_html(bot, bot.searchurl)
            if soup == -1:
                continue
            full = update_info(bot, soup)
            for i in range(0, len(full)):
                if not exists_in_old(full[i], old_full) and not init["first_join"]:
                    msg_send(bot.irc, bot.channel, "["+bot.botnick+"] "+full[i][0]+" made a new post in thread: "+full[i][1]+" ("+full[i][2]+") -- "+full[i][3])
            if init["first_join"]:
                init["first_join"] = False
            old_full = full
            finish_time = time.time() + 60

    return 0

def channel_join(bot):
    bot.irc.send(bytes("JOIN " + bot.channel + "\n", "UTF-8"))

def check_for_bblquit(bot, user, text):
    if text.find(bot.channel) != -1:
        substring = text.split(bot.channel)[1][2:]
        if substring == "bbl" and bot.state["greeter"]:
            chance = random.randint(1, 100)
            if chance > 55:
                msg_send(bot.irc, bot.channel, "fuck off "+user)
            else:
                msg_send(bot.irc, bot.channel, "bbl "+user)

def check_for_command(bot, user, text):
    if bot.state["op-only"] and not is_op(bot, user):
        return
    if text.find("."+bot.botnick) != -1:
        raw = text.split(bot.channel)[1][2:]
        if raw == "."+bot.botnick:
            execute_command(bot, ["help"], user)
        else:
            str_split = raw.split(None, 2)
            if str_split[0] == "."+bot.botnick:
                if len(str_split) > 1:
                    execute_command(bot, str_split[1:], user)

def check_for_jambo(bot, user, text):
    if text.find(bot.channel) != -1 and user == "djindy":
        substring = text.split(bot.channel)[1][2:]
        if substring.lower() == "jambo":
            msg_send(bot.irc, bot.channel, "mambo")

def check_for_user_entry(bot, user, text):
    if text.find(bot.channel) != -1:
        substring = text.split(bot.channel)[0]
        if substring.find("JOIN") != -1:
            bot.names.append(user)
            if bot.state["greeter"] and user != bot.botnick:
                msg_send(bot.irc, bot.channel, "hi "+user)

def check_for_user_mode(bot, user, text):
    if user == "JNET" and text.find("MODE") != -1:
        if len(text.split("+v ")) > 1:
            name = text.split("+v ")[1]
            bot.names.remove(name)
            bot.names.append("+"+name)
        if len(text.split("+o ")) > 1:
            name = text.split("+o ")[1]
            bot.names.remove(name)
            bot.names.append("@"+name)

def check_for_user_exit(bot, user, text):
    if text.find("QUIT") != -1 and text.find(bot.channel) == -1:
        if user.lower() == "jeckidy":
            bot.state["ragequits"] += 1
            msg_send(bot.irc, bot.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
            with open("bot_state.txt", "w") as json_file:
                json.dump(bot.state, json_file)
        if is_op(bot, user):
            bot.names.remove("@"+user)
        elif is_voice(bot, user):
            bot.names.remove("+"+user)
        else:
            bot.names.remove(user)
    elif text.find("PART") != -1 and text.find(bot.channel) == -1:
        if user.lower() == "jeckidy":
            bot.state["ragequits"] += 1
            msg_send(bot.irc, bot.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
            with open("bot_state.txt", "w") as json_file:
                json.dump(bot.state, json_file)
        if is_op(bot, user):
            bot.names.remove("@"+user)
        elif is_voice(bot, user):
            bot.names.remove("+"+user)
        else:
            bot.names.remove(user)

def check_text(bot, init, text):
    if text == "":
        return
    elif text[:4] == "PING":
        reply_pong(bot.irc, text)
    elif init["fully_started"]:
        user = get_user(text)
        if user != None:
            check_for_user_mode(bot, user, text)
            check_for_user_entry(bot, user, text)
            check_for_bblquit(bot, user, text)
            check_for_user_exit(bot, user, text)
            check_for_command(bot, user, text)
            check_for_jambo(bot, user, text)

def execute_command(bot, str_split, user):
    command = str_split[0]
    arguments = ""
    if len(str_split) > 1:
        arguments = str_split[1]
    if command == "echo" and arguments != "":
        msg_send(bot.irc, bot.channel, arguments)
    elif command == "help" and arguments == "":
        msg_send(bot.irc, bot.channel, "Usage: ."+bot.botnick+" [command] [arguments]")
        msg_send(bot.irc, bot.channel, "Type '."+bot.botnick+" help [command]' for more details about a particular command")
        msg_send(bot.irc, bot.channel, "Available commands: echo, help, kill, list, random, reboot, set, show, update")
    elif command == "help" and arguments != "":
        if arguments == "echo":
            msg_send(bot.irc, bot.channel, "echo [message] -- tell the bot echo back a message")
        if arguments == "help":
            msg_send(bot.irc, bot.channel, "help [command (optional)] -- display detailed help output for a particular command")
        if arguments == "kill":
            msg_send(bot.irc, bot.channel, "kill [timeout (optional)] -- kill the bot with an optional timeout (channel op only)")
        if arguments == "list":
            msg_send(bot.irc, bot.channel, "list [actions|properties] -- list all actions/properties with a short description")
        if arguments == "random":
            msg_send(bot.irc, bot.channel, "random [action] -- randomize a certain action")
        if arguments == "reboot":
            msg_send(bot.irc, bot.channel, "reboot [timeout (optional)] reboot the bot with an optional timeout (channel op only)")
        if arguments == "set":
            msg_send(bot.irc, bot.channel, "set [property] [value] -- set one of the bot's properties to a particular value (channel op only)")
        if arguments == "show":
            msg_send(bot.irc, bot.channel, "show [property] -- show the value of one of the bot's properties")
        if arguments == "update":
            msg_send(bot.irc, bot.channel, "update -- pull the latest changes from git (channel op only)")
    elif command == "kill":
        if is_op(bot, user):
            if arguments != "" and only_numbers(arguments):
                bot.state["timestamp"] = time.time()
                bot.state["timeout"] = int(arguments)
                msg_send(bot.irc, bot.channel, "Dying in "+arguments+" seconds")
            elif arguments != "" and not only_numbers(arguments):
                msg_send(bot.irc, bot.channel, "Error: timeout must be an integer value")
                return
            bot.state["kill"] = True
        else:
            msg_send(bot.irc, bot.channel, "Only channel ops can kill me.")
    elif command == "list" and arguments != "":
        if arguments == "actions":
            msg_send(bot.irc, bot.channel, "thread -- retrieve a thread from the forum")
        elif arguments == "properties":
            msg_send(bot.irc, bot.channel, "greeter -- greet users on entry (boolean: on/off)")
            msg_send(bot.irc, bot.channel, "op-only -- only listen to commands from channel ops (boolean: on/off)")
            msg_send(bot.irc, bot.channel, "ragequits -- ragequit counter (integer)")
    elif command == "reboot":
        if is_op(bot, user):
            if arguments != "" and only_numbers(arguments):
                bot.state["timestamp"] = time.time()
                bot.state["timeout"] = int(arguments[0])
                msg_send(bot.irc, bot.channel, "Rebooting in "+arguments[0]+" seconds")
            elif arguments != "" and not only_numbers(arguments):
                msg_send(bot.irc, bot.channel, "Error: timeout must be an integer value")
                return
            bot.state["reboot"] = True
        else:
            msg_send(bot.irc, bot.channel, "Only channel ops can reboot me.")
    elif command == "random" and arguments != "":
        if arguments == "thread":
            # add this mysterious constant that exists for unknown reasons but whatever
            thread_count = get_thread_count(bot) + 803
            rand_soup = -1
            while rand_soup == -1:
                rand_tid = random.randint(1, thread_count)
                rand_url = bot.baseurl+str(rand_tid)
                rand_soup = get_html(bot, rand_url)
            thread_title = rand_soup.find("title").contents[0]
            msg_send(bot.irc, bot.channel, "Random thread: "+thread_title+" -- "+rand_url)
    elif command == "set" and arguments != "":
        if not is_op(bot, user):
            msg_send(bot.irc, bot.channel, "Only channel ops can use the set command.")
            return
        arguments = arguments.split()
        if arguments[0] == "greeter":
            if arguments[1] == "on":
                bot.state["greeter"] = True
                msg_send(bot.irc, bot.channel, "User greeter turned on")
            elif arguments[1] == "off":
                bot.state["greeter"] = False
                msg_send(bot.irc, bot.channel, "User greeter turned off")
        elif arguments[0] == "op-only":
            if arguments[1] == "on":
                bot.state["op-only"] = True
                msg_send(bot.irc, bot.channel, "Only listening to commands from channel ops")
            elif arguments[1] == "off":
                bot.state["op-only"] = False
                msg_send(bot.irc, bot.channel, "Listening to commands from all users")
        elif arguments[0] == "ragequits":
            if only_numbers(arguments[1]):
                bot.state["ragequits"] = int(arguments[1])
                msg_send(bot.irc, bot.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
            else:
                msg_send(bot.irc, bot.channel, "Error: ragequits can only be set to an integer value")
    elif command == "show" and arguments != "":
        if arguments == "greeter":
            if bot.state["greeter"]:
                msg_send(bot.irc, bot.channel, "User greeter turned on")
            else:
                msg_send(bot.irc, bot.channel, "User greeter turned off")
        elif arguments == "op-only":
            if bot.state["op-only"]:
                msg_send(bot.irc, bot.channel, "op-only is turned on")
            else:
                msg_send(bot.irc, bot.channel, "op-only is turned off")
        elif arguments == "ragequits":
            msg_send(bot.irc, bot.channel, "The ragequit counter is at "+str(bot.state["ragequits"]))
    elif command == "update" and arguments == "":
        if not is_op(bot, user):
            msg_send(bot.irc, bot.channel, "Only channel ops can use the update command.")
            return
        msg_send(bot.irc, bot.channel, "Pulling the latest changes from git")
        os.system("git pull")

def exists_in_old(item, old_full):
    for i in range(0, len(old_full)):
        if item == old_full[i]:
            return True
    return False

def get_html(bot, url):
    try:
        html = bot.br.open(url).read()
        soup = BeautifulSoup(html, "html.parser")
        return soup
    except:
        return -1

def get_names(bot, text):
    if text.find(bot.channel) != -1:
        str_split = text.split(bot.channel)
        if str_split[0].find(bot.botnick+" *") != -1 and str_split[1].find(bot.botnick) != -1:
            bot.names = str_split[1][2:].split()

def get_response(irc):
    try:
        resp = irc.recv(4096).decode("UTF-8").rstrip("\r\n")
        return resp
    except:
        return ""

def get_thread_count(bot):
    soup = get_html(bot, bot.statsurl)
    return int(soup.find_all("td")[3].find_all("strong")[1].contents[0].replace(",",""))

def get_user(text):
    if text.find("!") != -1:
        return text.split("!")[0][1:]

def identify_name(bot, text):
    bot.irc.send(bytes("PRIVMSG NickServ@services.rizon.net :IDENTIFY "+bot.botpass+"\r\n", "UTF-8"))

def is_op(bot, user):
    for i in bot.names:
        if i[0] == "@" and user == i[1:]:
            return True
    return False

def is_voice(bot, user):
    for i in bot.names:
        if i[0] == "+" and user == i[1:]:
            return True
    return False

def mechanize_login(bot):
    cj = http.cookiejar.CookieJar()

    bot.br = mechanize.Browser()
    bot.br.set_cookiejar(cj)
    bot.br.set_handle_equiv(True)
    bot.br.set_handle_gzip(True)
    bot.br.set_handle_redirect(True)
    bot.br.set_handle_referer(True)
    bot.br.set_handle_robots(False)
    bot.br.set_handle_refresh(mechanize._http.HTTPRefreshProcessor(), max_time=1)
    bot.br.addheaders = [("User-agent", "Mozilla/5.0 (Windows NT 10.0; rv:68.0) Gecko/20100101 Firefox/68.0")]

    bot.br.open(bot.loginurl)
    bot.br.select_form(nr=1)
    if bot.botpass == "":
        bot.br.form["username"] = input("Username: ")
        bot.br.form["password"] = getpass.getpass("Password: ")
        bot.botpass = bot.br.form['password']
    else:
        bot.br.form["username"] = bot.botnick
        bot.br.form["password"] = bot.botpass
    return bot.br,bot.botpass

def msg_send(irc, channel, msg):
    irc.send(bytes("PRIVMSG " + channel + " :" + msg + "\n", "UTF-8"))

def only_numbers(string):
    for i in string:
        if not i.isdigit():
            return False
    return True

def reply_pong(irc, text):
    for i in range(len(text.split())):
        if text.split()[i] == "PING":
            irc.send(bytes('PONG '+text.split()[i+1]+'\r\n', "UTF-8"))

def server_connect(irc, server, port, botnick):
    print("Connecting to: " + server)
    irc.connect((server, port))
    irc.send(bytes("USER " + botnick + " " + botnick +" " + botnick + " :python\n", "UTF-8"))
    irc.send(bytes("NICK " + botnick + "\n", "UTF-8"))

def update_info(bot, soup):
    poster = []
    thread = []
    time = []
    url = []
    poster_names = soup.find_all("span", class_="smalltext")
    thread_names = soup.find_all("a", {"id" : re.compile("tid_.*")})
    for i in range(len(poster_names)-1, -1, -1):
        if poster_names[i].strong != None and poster_names[i].span != None:
            if str(poster_names[i].a).find("search.php") > -1:
                continue
            poster.append(poster_names[i].strong.contents[0])
    for i in range(len(thread_names)-1, -1, -1):
        thread.append(thread_names[i].contents[0])
    for i in range(len(poster_names)-1, -1, -1):
        if poster_names[i].span != None and str(poster_names[i].a).find("search.php") == -1:
            time.append(poster_names[i].contents[2][2:])
    for i in range(len(thread_names)-1, -1, -1):
        thread_id = thread_names[i].get('id')[4:]
        url.append(bot.baseurl+thread_id+"&action=lastpost")
    full = []
    for i in range(len(poster)):
        full.append([poster[i], thread[i], time[i], url[i]])
    return full

if __name__ == "__main__":
    main()
