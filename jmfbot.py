#!/usr/bin/env python3

import argparse
import getpass
import http.cookiejar
import mechanize
import os
import random
import re
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
    port = ""
    server = ""
    ssl = ""

    irc = ""

    state = {
        "connected" : False,
        "first_join" : True,
        "fully_started" : False,
        "greeter" : True,
        "identified" : False,
        "identify" : True,
        "in_channel" : False,
        "kill" : False,
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

    old_full = []
    old_time = 0

    while True:
        if not bot.state["connected"]:
            bot.irc = socket.socket()
            if bot.state["ssl"]:
                bot.irc = ssl.wrap_socket(bot.irc)
            server_connect(bot.irc, bot.server, bot.port, bot.botnick)
            bot.state["connected"] = True

        if bot.state["connected"]:
            text = get_response(bot.irc)
            print(text)

        elapsed_time = time.time() - old_time

        check_text(bot, text)

        if not bot.state["fully_started"]:
            if not bot.state["identified"] and bot.state["identify"]:
                identify_name(bot, text)
                if text.find("Password incorrect.") != -1:
                    bot.botpass = getpass.getpass("Password: ")

            if bot.state["identify"]:
                if text.find('+r') != -1:                      
                    channel_join(bot)
                if text.find('+v') != -1:
                    msg_send(bot.irc, bot.channel, "hi")
                    bot.state["fully_started"] = True
            else:
                if text.find("Own a large/active channel") != -1:
                    channel_join(bot)
                if text.find("End of /NAMES list.") != -1:
                    msg_send(bot.irc, bot.channel, "hi")
                    bot.state["fully_started"] = True
            continue

        if bot.state["kill"]:
            if time.time() >= bot.state["timestamp"] + bot.state["timeout"]:
                msg_send(bot.irc, bot.channel, "bbl")
                time.sleep(1)
                bot.irc.shutdown(0)
                bot.irc.close()
                break

        if bot.state["reboot"]:
            if time.time() >= bot.state["timestamp"] + bot.state["timeout"]:
                msg_send(bot.irc, bot.channel, "brb")
                time.sleep(1)
                bot.irc.shutdown(0)
                bot.irc.close()
                os.execl("./jmfbot.py", "--botnick="+bot.botnick, "--botpass="+bot.botpass, "--channel="+bot.channel,
                         "--identify="+str(args.identify), "--server="+bot.server, "--ssl="+str(args.ssl))

        if bot.state["fully_started"] and elapsed_time > 60:
            soup = get_html(bot, bot.searchurl)
            full = update_info(bot, soup)
            for i in range(0, len(full)):
                if not exists_in_old(full[i], old_full) and not bot.state["first_join"]:
                    msg_send(bot.irc, bot.channel, "["+bot.botnick+"] "+full[i][0]+" made a new post in thread: "+full[i][1]+" ("+full[i][2]+") -- "+full[i][3])
                    time.sleep(1)
            if bot.state["first_join"]:
                bot.state["first_join"] = False
            old_full = full
            old_time = time.time()

        time.sleep(5)

    return 0

def channel_join(bot):
    time.sleep(1)
    bot.irc.send(bytes("JOIN " + bot.channel + "\n", "UTF-8"))
    bot.state["in_channel"] = True

def check_for_bblquit(bot, user, text):
    if text.find(bot.channel) != -1:
        substring = text.split(bot.channel)[1][2:]
        if substring == "bbl":
            msg_send(bot.irc, bot.channel, "bbl "+user)

def check_for_command(bot, user, text):
    if text.find("."+bot.botnick+" ") != -1:
        raw = text.split(bot.channel)[1][2:]
        str_split = raw.split(None, 2)
        if str_split[0] == "."+bot.botnick:
            if len(str_split) > 1:
                execute_command(bot, str_split[1:], user)
            else:
                execute_command(bot, ["help"], user)

def check_for_ragequit(bot, user, text):
    if user.lower() == "jeckidy" and text.find("QUIT") != 1 and text.find(bot.channel) == -1:
        bot.state["ragequits"] += 1
        msg_send(bot.irc, bot.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))

def check_for_user_entry(bot, user, text):
    if text.find(bot.channel) != -1:
        substring = text.split(bot.channel)[0]
        if substring.find("JOIN") != -1 and user != bot.botnick:
                msg_send(bot.irc, bot.channel, "hi "+user)

def check_text(bot, text):
    if text[:4] == "PING":
        reply_pong(bot.irc, text)
    else:
        user = get_user(text)
        if user != None:
            check_for_command(bot, user, text)
            check_for_ragequit(bot, user, text)
            if bot.state["greeter"]:
                check_for_bblquit(bot, user, text)
                check_for_user_entry(bot, user, text)

def execute_command(bot, str_split, user):
    command = str_split[0]
    arguments = ""
    if len(str_split) > 1:
        arguments = str_split[1]
    if command == "echo" and arguments != "":
        msg_send(bot.irc, bot.channel, arguments)
    elif command == "help" and arguments == "":
        msg_send(bot.irc, bot.channel, "Usage: ."+bot.botnick+" [command] [arguments]")
        time.sleep(1)
        msg_send(bot.irc, bot.channel, "Type '."+bot.botnick+" help [command]' for more details about a particular command")
        time.sleep(1)
        msg_send(bot.irc, bot.channel, "Available commands: echo, help, kill, list, random, set, show")
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
            msg_send(bot.irc, bot.channel, "reboot [timeout (optional)] -- reboot the bot with an optional timeout (channel op only)")
        if arguments == "set":
            msg_send(bot.irc, bot.channel, "set [property] [value] -- set one of the bot's properties to a particular value (channel op only)")
        if arguments == "show":
            msg_send(bot.irc, bot.channel, "show [property] -- show the value of one of the bot's properties")
    elif command == "kill":
        if is_op(bot.irc, bot.channel, user):
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
            time.sleep(1)
            msg_send(bot.irc, bot.channel, "ragequits -- ragequit counter (integer)")
    elif command == "reboot":
        if is_op(bot.irc, bot.channel, user):
            if arguments != "" and only_numbers(arguments):
                bot.state["timestamp"] = time.time()
                bot.state["timeout"] = int(arguments)
                msg_send(bot.irc, bot.channel, "Rebooting in "+arguments+" seconds")
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
                time.sleep(1)
                rand_tid = random.randint(1, thread_count)
                rand_url = bot.baseurl+str(rand_tid)
                rand_soup = get_html(bot, rand_url)
            thread_title = rand_soup.find("title").contents[0]
            msg_send(bot.irc, bot.channel, "Random thread: "+thread_title+" -- "+rand_url)
    elif command == "set" and arguments != "":
        if not is_op(bot.irc, bot.channel, user):
            msg_send(bot.irc, bot.channel, "Only channel ops can use the set command.")
        arguments = arguments.split()
        if arguments[0] == "greeter":
            if arguments[1] == "on":
                bot.state["greeter"] = True
                msg_send(bot.irc, bot.channel, "User greeter turned on")
            elif arguments[1] == "off":
                bot.state["greeter"] = False
                msg_send(bot.irc, bot.channel, "User greeter turned off")
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
        if arguments == "ragequits":
            msg_send(bot.irc, bot.channel, "The ragequit counter is at "+str(bot.state["ragequits"]))

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

def get_response(irc):
    resp = irc.recv(4096).decode("UTF-8").rstrip("\r\n")
    return resp

def get_thread_count(bot):
    soup = get_html(bot, bot.statsurl)
    return int(soup.find_all("td")[3].find_all("strong")[1].contents[0].replace(",",""))

def get_user(text):
    if text.find("!") != -1:
        return text.split("!")[0][1:]

def identify_name(bot, text):
    if text.find('PING') != -1:
        bot.irc.send(bytes("PRIVMSG NickServ@services.rizon.net :IDENTIFY "+bot.botpass+"\r\n", "UTF-8"))
        bot.state["identified"] = True

def is_op(irc, channel, user):
    irc.send(bytes("NAMES " + channel + "\n", "UTF-8"))
    names = get_response(irc)
    names = names.split()
    for i in names:
        if i[0] == "@" and user == i[1:]:
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
    time.sleep(5)

def update_info(bot, soup):
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
        url.append(bot.baseurl+thread_id+"&action=lastpost")
    full = []
    for i in range(len(poster)):
        full.append([poster[i], thread[i], time[i], url[i]])
    return full

if __name__ == "__main__":
    main()
