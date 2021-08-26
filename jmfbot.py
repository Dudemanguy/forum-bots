#!/usr/bin/env python3

import argparse
import getpass
import http.cookiejar
import json
import math
import mechanize
import os
import random
import re
import requests
import select
import socket
import ssl
import time
from bs4 import BeautifulSoup

class irc_bot():
    baseurl = "https://japanesemetalforum.com/showthread.php?tid="
    loginurl = "https://japanesemetalforum.com/member.php?action=login"
    searchurl = "https://japanesemetalforum.com/search.php?action=getdaily"
    statsurl = "https://japanesemetalforum.com/stats.php"

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
        "greeter-blacklist" : "",
        "identify" : True,
        "kill" : False,
        "op-only": False,
        "quiz": {},
        "quiz_current": {"question": "", "answer": "", "hint": "", "hint_level": 0},
        "quiz_iterator": 0,
        "quiz_questions": [],
        "quiz_score": {},
        "quiz_size": 0,
        "quiz_state": False,
        "ragequits" : 0,
        "reboot" : False,
        "sleep_interval" : 60,
        "ssl" : True,
        "wakeup_time": 0
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
        f = open("bot_state.txt", "r")
        lines = f.readlines()
        bot.state["ragequits"] = int(lines[0].strip())
        bot.state["greeter-blacklist"] = lines[1].strip()
        f.close();

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

    bot.state["wakeup_time"] = time.time() + bot.state["sleep_interval"]
    timeout = bot.state["sleep_interval"]*1000

    bot.irc.setblocking(0)

    while True:
        current_time = time.time()
        if current_time < bot.state["wakeup_time"]:
            timeout = (bot.state["wakeup_time"] - current_time)*1000
        bot.poller.poll(timeout)
        text = get_response(bot.irc)

        check_text(bot, init, text)

        if not init["fully_started"]:
            if bot.state["identify"]:
                if text.find("please choose a different nick") != -1:
                    identify_name(bot, text)
                    init["identified"] = True

            if init["identified"]:
                if text.find('+r') != -1:                      
                    channel_join(bot)
                if text.find(bot.botnick+" @ "+bot.channel) != -1: 
                    get_names(bot, text)
                if text.find('+v') != -1:
                    msg_send(bot.irc, bot.channel, "hi")
                    init["fully_started"] = True
            else:
                if text.find("Own a large/active channel") != -1:
                    channel_join(bot)
                if text.find(bot.botnick+" @ "+bot.channel) != -1: 
                    get_names(bot, text)
                if text.find("End of /NAMES list.") != -1:
                    msg_send(bot.irc, bot.channel, "hi")
                    init["fully_started"] = True

        if bot.state["kill"]:
            if time.time() >= bot.state["wakeup_time"]:
                bot.state["kill"] = False
                write_bot_state(bot)
                msg_send(bot.irc, bot.channel, "bbl")
                bot.irc.setblocking(1)
                bot.irc.shutdown(0)
                bot.irc.close()
                break

        if bot.state["quiz_state"]:
            if time.time() >= bot.state["wakeup_time"]:
                if bot.state["quiz_current"]["hint_level"] == 3:
                    msg_send(bot.irc, bot.channel, "The correct answer was " + bot.state["quiz_current"]["answer"] + ".")
                    if bot.state["quiz_iterator"] == bot.state["quiz_size"]:
                        bot.state["quiz_state"] = False
                        bot.state["sleep_interval"] = 60
                        if bot.state["quiz_score"] == {}:
                            msg_send(bot.irc, bot.channel, "Quiz finished. Wow, no one won. You guys suck.")
                        else:
                            winner = max(bot.state["quiz_score"], key=bot.state["quiz_score"].get)
                            score = bot.state["quiz_score"][winner]
                            msg_send(bot.irc, bot.channel, "Quiz finished. Winner is " + winner + " with a score of " + str(score) + ".")
                    else:
                        quiz_new_question(bot)
                    continue
                bot.state["quiz_current"]["hint_level"] += 1
                quiz_display_hint(bot)

        if bot.state["reboot"]:
            if time.time() >= bot.state["wakeup_time"]:
                bot.state["reboot"] = False
                write_bot_state(bot)
                msg_send(bot.irc, bot.channel, "brb")
                bot.irc.setblocking(1)
                bot.irc.shutdown(0)
                bot.irc.close()
                os.execl("jmfbot.py", "--botnick="+bot.botnick, "--botpass="+bot.botpass)

        if init["fully_started"] and time.time() >= bot.state["wakeup_time"]:
            soup = get_html_mechanize(bot, bot.searchurl)
            if soup == -1:
                continue
            full = update_info(bot, soup)
            for i in range(0, len(full)):
                if not exists_in_old(full[i], old_full) and not init["first_join"]:
                    msg_send(bot.irc, bot.channel, "["+bot.botnick+"] "+full[i][0]+" made a new post in thread: "+full[i][1]+" ("+full[i][2]+") -- "+full[i][3])
            if init["first_join"]:
                init["first_join"] = False
            old_full = full
            bot.state["wakeup_time"] = time.time() + bot.state["sleep_interval"]

    return 0

def channel_join(bot):
    bot.irc.send(bytes("JOIN " + bot.channel + "\n", "UTF-8"))

def check_for_bblquit(bot, user, text):
    if text.find(bot.channel) != -1:
        substring = text.split(bot.channel)[1][2:]
        if substring == "bbl":
            chance = random.randint(1, 100)
            if chance > 55:
                msg_send(bot.irc, bot.channel, "fuck off "+user)
            else:
                msg_send(bot.irc, bot.channel, "bbl "+user)

def check_for_command(bot, user, text):
    if bot.state["op-only"] and not is_op(bot, user):
        return
    command = ""
    if text.find("PRIVMSG "+bot.botnick) != -1:
        command = text.split(bot.botnick)[1][2:]
        command = "."+bot.botnick+" "+command
    elif text.find("."+bot.botnick) != -1:
        command = text.split(bot.channel)[1][2:]
    if command[0:7] == "."+bot.botnick:
        execute_command(bot, command[8:], user)

def check_for_jambo(bot, user, text):
    if text.find(bot.channel) != -1 and user == "djindy":
        substring = text.split(bot.channel)[1][2:]
        if substring.lower() == "jambo":
            msg_send(bot.irc, bot.channel, "mambo")

def check_for_url(bot, user, text):
    if len(text.split(bot.channel+" :")) != 2:
        return
    string = text.split(bot.channel+" :")[1]
    if string.find("http") != -1 or re.search("www", string):
        split = string.split()
        for substring in split:
            if substring.find("http") != -1 or re.search("www", substring):
                if substring.find("http") == -1:
                    substring = "https://"+substring
                if substring.find("mobile.twitter.com") != -1:
                    substring = substring.replace("mobile.twitter.com", "nitter.pussthecat.org")
                elif substring.find("twitter.com") != -1:
                    substring = substring.replace("twitter.com", "nitter.pussthecat.org")
                if substring.find("m.youtube.com") != -1:
                    substring = substring.replace("m.youtube.com", "yewtu.be")
                    substring = substring.replace("www.", "")
                elif substring.find("youtube.com") != -1:
                    substring = substring.replace("youtube.com", "yewtu.be")
                    substring = substring.replace("www.", "")
                elif substring.find("youtu.be") != -1:
                    substring = substring.replace("youtu.be", "yewtu.be")
                    substring = substring.replace("www.", "")
                soup = get_html_requests(bot, substring)
                if soup == -1:
                    continue
                if soup.find("title").contents:
                    msg_send(bot.irc, bot.channel, "[Title] "+soup.find("title").contents[0].strip())

def check_for_nick_change(bot, user, text):
    if text.find("NICK") != -1 and text.find(bot.channel) == -1:
        new_nick = text.split("NICK :")[1]
        for name in bot.names:
            if name == user or name == user[1:]:
                bot.names.remove(name)
                bot.names.append(new_nick)

def check_for_quiz_answer(bot, user, text):
    if bot.state["quiz_current"]["answer"].lower() in text.lower():
        msg_send(bot.irc, bot.channel, 
            "Winner: " + user + "; Answer: "+bot.state["quiz_current"]["answer"])
        if user in bot.state["quiz_score"]:
            bot.state["quiz_score"][user] += 1
        else:
            bot.state["quiz_score"][user] = 1
        bot.state["quiz_current"]["hint_level"] = 3
        bot.state["wakeup_time"] = time.time()

def check_for_user_entry(bot, user, text):
    if text.find(bot.channel) != -1:
        substring = text.split(bot.channel)[0]
        if substring.find("JOIN") != -1:
            bot.names.append(user)
            blacklist = bot.state["greeter-blacklist"].split(",")
            if bot.state["greeter"] and not user in blacklist:
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
            write_bot_state(bot)
        if is_op(bot, user):
            if "@"+user in bot.names:
                bot.names.remove("@"+user)
        elif is_voice(bot, user):
            if "+"+user in bot.names:
                bot.names.remove("+"+user)
        else:
            if user in bot.names:
                bot.names.remove(user)
    elif text.find("PART") != -1 and text.find(bot.channel) == -1:
        if user.lower() == "jeckidy":
            bot.state["ragequits"] += 1
            msg_send(bot.irc, bot.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
            write_bot_state(bot)
        if is_op(bot, user):
            if "@"+user in bot.names:
                bot.names.remove("@"+user)
        elif is_voice(bot, user):
            if "+"+user in bot.names:
                bot.names.remove("+"+user)
        else:
            if user in bot.names:
                bot.names.remove(user)

def check_text(bot, init, text):
    if text == "":
        return
    elif text[:4] == "PING":
        reply_pong(bot.irc, text)
    elif text.find("Password incorrect.") != -1:
        bot.botpass = getpass.getpass("Password: ")
        init["identified"] = False
    elif init["fully_started"]:
        user = get_user(text)
        if user != None:
            check_for_user_mode(bot, user, text)
            check_for_user_entry(bot, user, text)
            check_for_nick_change(bot, user, text)
            check_for_bblquit(bot, user, text)
            check_for_user_exit(bot, user, text)
            check_for_command(bot, user, text)
            check_for_url(bot, user, text)
            check_for_jambo(bot, user, text)
        if bot.state["quiz_state"]:
            check_for_quiz_answer(bot, user, text)

def execute_command(bot, command, user):
    if command[0:4] == "dice":
        args = command.split()[1:]
        execute_dice_command(bot, args, user)
    elif command[0:4] == "echo":
        args = command.split(None, 1)[1]
        execute_echo_command(bot, args, user)
    elif command[0:4] == "help" or command == "":
        args = command.split()[1:]
        execute_help_command(bot, args, user)
    elif command[0:4] == "kill":
        args = command.split()[1:]
        execute_kill_command(bot, args, user)
    elif command[0:2] == "me":
        args = command.split(None, 1)[1]
        execute_me_command(bot, args, user)
    elif command[0:4] == "pull":
        args = command.split()[1:]
        execute_pull_command(bot, args, user)
    elif command[0:4] == "quiz":
        args = command.split()[1:]
        execute_quiz_command(bot, args, user)
    elif command[0:6] == "reboot":
        args = command.split()[1:]
        execute_reboot_command(bot, args, user)
    elif command[0:3] == "set":
        args = command.split()[1:]
        execute_set_command(bot, args, user)
    elif command[0:4] == "show":
        args = command.split()[1:]
        execute_show_command(bot, args, user)
    elif command[0:6] == "thread":
        args = command.split()[1:]
        execute_thread_command(bot, args, user)

def execute_dice_command(bot, args, user):
    if args == []:
        size = 10
    elif args[0].isdigit():
        size = int(args[0])
    else:
        return
    roll = random.randint(1, size)
    msg_send(bot.irc, bot.channel, str(roll))

def execute_echo_command(bot, args, user):
    msg_send(bot.irc, bot.channel, args)

def execute_help_command(bot, args, user):
    if args == []:
        msg_send(bot.irc, bot.channel, "Usage: execute the bot with either ."+bot.botnick+" or /msg "+bot.botnick+" followed by [command] [arguments]")
        msg_send(bot.irc, bot.channel, "Try '[execute] help [command]' for more details about a particular command")
        msg_send(bot.irc, bot.channel, "Available commands: dice, echo, help, kill, me, pull, quiz, reboot, set, show, thread")
        return
    if args[0] == "dice":
        msg_send(bot.irc, bot.channel, "dice [size (optional)] -- roll a dice with a certain size (default 10)")
    if args[0] == "echo":
        msg_send(bot.irc, bot.channel, "echo [message] -- tell the bot echo back a message")
    if args[0] == "help":
        msg_send(bot.irc, bot.channel, "help [command (optional)] -- display detailed help output for a particular command")
    if args[0] == "kill":
        msg_send(bot.irc, bot.channel, "kill [timeout (optional)] -- kill the bot with an optional timeout (channel op only)")
    if args[0] == "me":
        msg_send(bot.irc, bot.channel, "me [message] -- tell the bot to send a message with /me")
    if args[0] == "pull":
        msg_send(bot.irc, bot.channel, "pull -- pull the latest changes from git (channel op only)")
    if args[0] == "quiz":
        msg_send(bot.irc, bot.channel, "quiz [file] [number (optional)] -- start a locally stored quiz with the bot with an optional number of questions (default 10)")
    if args[0] == "reboot":
        msg_send(bot.irc, bot.channel, "reboot [timeout (optional)] reboot the bot with an optional timeout (channel op only)")
    if args[0] == "set":
        msg_send(bot.irc, bot.channel, "set [property] [value] -- set one of the bot's properties to a particular value (channel op only)")
    if args[0] == "show":
        msg_send(bot.irc, bot.channel, "show [property] -- show the value of one of the bot's properties")
    if args[0] == "thread":
        msg_send(bot.irc, bot.channel, "thread [random/integer (optional)] -- get a random thread (default) or optionally specifiy one with an integer")

def execute_kill_command(bot, args, user):
    if is_op(bot, user):
        if args != [] and only_numbers(args[0]):
            bot.state["wakeup_time"] = time.time() + int(args[0])
            msg_send(bot.irc, bot.channel, "Dying in "+args[0]+" seconds")
        elif args != [] and not only_numbers(args[0]):
            msg_send(bot.irc, bot.channel, "Error: timeout must be an integer value")
            return
        else:
            bot.state["wakeup_time"] = time.time()
        bot.state["kill"] = True
    else:
        msg_send(bot.irc, bot.channel, "Only channel ops can kill me.")

def execute_me_command(bot, args, user):
    msg_me(bot.irc, bot.channel, args)

def execute_pull_command(bot, args, user):
    if not is_op(bot, user):
        msg_send(bot.irc, bot.channel, "Only channel ops can use the pull command.")
        return
    msg_send(bot.irc, bot.channel, "Pulling the latest changes from git")
    os.system("git pull")

def execute_quiz_command(bot, args, user):
    if args == []:
        return
    if len(args) > 1 and args[1].isdigit():
        size = int(args[1])
    else:
        size = 10
    quiz_file = args[0] + ".json"
    if os.path.isfile(quiz_file):
        with open(quiz_file) as f:
            bot.state["quiz"] = json.load(f, encoding="utf-8")
        if size > len(bot.state["quiz"]):
            size = len(bot.state["quiz"])
        msg_send(bot.irc, bot.channel, "Starting quiz " + args[0] + ".")
        bot.state["quiz_size"] = size
        bot.state["quiz_state"] = True
        bot.state["sleep_interval"] = 10
        bot.state["wakeup_time"] = time.time() + bot.state["sleep_interval"]
        quiz_new_question(bot)
    else:
        msg_send(bot.irc, bot.channel, quiz_file + " was not found!")

def execute_reboot_command(bot, args, user):
    if is_op(bot, user):
        if args != [] and only_numbers(args[0]):
            bot.state["wakeup_time"] = time.time() + int(args[0])
            msg_send(bot.irc, bot.channel, "Rebooting in "+args[0]+" seconds")
        elif args != [] and not only_numbers(args[0]):
            msg_send(bot.irc, bot.channel, "Error: timeout must be an integer value")
            return
        else:
            bot.state["wakeup_time"] = time.time()
        bot.state["reboot"] = True
    else:
        msg_send(bot.irc, bot.channel, "Only channel ops can reboot me.")

def execute_set_command(bot, args, user):
    if not is_op(bot, user):
        msg_send(bot.irc, bot.channel, "Only channel ops can use the set command.")
        return
    if args == []:
        return
    if args[0] == "greeter":
        if args[1] == "on":
            bot.state["greeter"] = True
            msg_send(bot.irc, bot.channel, "User greeter turned on")
        elif args[1] == "off":
            bot.state["greeter"] = False
            msg_send(bot.irc, bot.channel, "User greeter turned off")
    if args[0] == "greeter-blacklist" and len(args) == 2:
        bot.state["greeter-blacklist"] = args[1]
        msg_send(bot.irc, bot.channel, "User greeter blacklist set to '" + bot.state["greeter-blacklist"] + "'.")
    elif args[0] == "op-only":
        if args[1] == "on":
            bot.state["op-only"] = True
            msg_send(bot.irc, bot.channel, "Only listening to commands from channel ops")
        elif args[1] == "off":
            bot.state["op-only"] = False
            msg_send(bot.irc, bot.channel, "Listening to commands from all users")
    elif args[0] == "ragequits":
        if only_numbers(args[1]):
            bot.state["ragequits"] = int(args[1])
            msg_send(bot.irc, bot.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
        else:
            msg_send(bot.irc, bot.channel, "Error: ragequits can only be set to an integer value")

def execute_show_command(bot, args, user):
    if args == []:
        msg_send(bot.irc, bot.channel, "greeter -- greet users on entry (boolean: on/off)")
        msg_send(bot.irc, bot.channel, "greeter-blacklist -- exclude users from greeter (string: user1,user2,user3...)")
        msg_send(bot.irc, bot.channel, "op-only -- only listen to commands from channel ops (boolean: on/off)")
        msg_send(bot.irc, bot.channel, "ragequits -- ragequit counter (integer)")
    elif args[0] == "greeter":
        if bot.state["greeter"]:
            msg_send(bot.irc, bot.channel, "User greeter turned on")
        else:
            msg_send(bot.irc, bot.channel, "User greeter turned off")
    elif args[0] == "greeter-blacklist":
        msg_send(bot.irc, bot.channel, "The greeter blacklist is '" + bot.state["greeter-blacklist"]+"'.")
    elif args[0] == "op-only":
        if bot.state["op-only"]:
            msg_send(bot.irc, bot.channel, "op-only is turned on")
        else:
            msg_send(bot.irc, bot.channel, "op-only is turned off")
    elif args[0] == "ragequits":
        msg_send(bot.irc, bot.channel, "The ragequit counter is at "+str(bot.state["ragequits"]))

def execute_thread_command(bot, args, user):
    thread_url = ""
    thread_title = ""
    if args == [] or args[0] == "random":
        # add this mysterious constant that exists for unknown reasons but whatever
        thread_count = 4643
        if thread_count > 0:
            tid = random.randint(1, thread_count)
            thread_url = bot.baseurl+str(tid)
            thread_title = get_thread_title(bot, thread_url)
    elif args[0].isdigit():
        thread_url = bot.baseurl+args[0]
        thread_title = get_thread_title(bot, thread_url)
    if thread_title != "" and thread_url != "":
        msg_send(bot.irc, bot.channel, thread_title+" -- "+thread_url)

def exists_in_old(item, old_full):
    for i in range(0, len(old_full)):
        if item == old_full[i]:
            return True
    return False

def get_html_mechanize(bot, url):
    try:
        html = bot.br.open(url, timeout=30.0).read()
        soup = BeautifulSoup(html, "html.parser")
        return soup
    except:
        return -1

def get_html_requests(bot, url):
    try:
        headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 4.0.4; Galaxy Nexus Build/IMM76B) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.133 Mobile Safari/535.19"
        }
        html = requests.get(url, headers=headers).content.decode("UTF-8")
        soup = BeautifulSoup(html, "html.parser")
        return soup
    except:
        return -1

def get_names(bot, text):
    str_split = text.split(":"+bot.botnick+" ")
    for i in str_split[1].split():
        bot.names.append(i)

def get_response(irc):
    try:
        resp = irc.recv(4096).decode("UTF-8").rstrip("\r\n")
        return resp
    except:
        return ""

def get_thread_title(bot, url):
    soup = get_html_mechanize(bot, url)
    if soup == -1:
        msg_send(bot.irc, bot.channel, "Couldn't connect to thread page.")
        return ""
    return soup.find("title").contents[0]

def get_thread_count(bot):
    soup = get_html_mechanize(bot, bot.statsurl)
    if isinstance(soup, int):
        msg_send(bot.irc, bot.channel, "Couldn't connect to stats page.")
        return -1
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

def msg_me(irc, channel, msg):
    try:
        irc.send(bytes("PRIVMSG " + channel + " :\001ACTION " + msg + "\n", "UTF-8"))
    except:
        pass

def msg_send(irc, channel, msg):
    try:
        irc.send(bytes("PRIVMSG " + channel + " :" + msg + "\n", "UTF-8"))
    except:
        pass

def only_numbers(string):
    for i in string:
        if not i.isdigit():
            return False
    return True

def quiz_display_hint(bot):
    answer = bot.state["quiz_current"]["answer"]
    hint = bot.state["quiz_current"]["hint"]
    hint_level = bot.state["quiz_current"]["hint_level"]
    visible_chance = [0.05, 0.15, 0.25][hint_level - 1]
    for i in range(len(hint)):
        chance = random.randint(1, 100) / 100
        if hint[i] == "*" and chance < visible_chance:
            hint = hint[:i] + answer[i] + hint[i+1:]
    bot.state["quiz_current"]["hint"] = hint
    msg_send(bot.irc, bot.channel, "Hint: "+hint)

def quiz_new_question(bot):
    item = random.choice(list(bot.state["quiz"].items()))
    del bot.state["quiz"][item[0]]
    bot.state["quiz_iterator"] += 1
    bot.state["quiz_current"]["question"] = item[0]
    bot.state["quiz_current"]["answer"] = item[1]
    bot.state["quiz_current"]["hint"] = ""
    for i in range(len(bot.state["quiz_current"]["answer"])):
        if bot.state["quiz_current"]["answer"][i] == " ":
            bot.state["quiz_current"]["hint"] += " "
        else:
            bot.state["quiz_current"]["hint"] += "*"
    bot.state["quiz_current"]["hint_level"] = 0
    msg_send(bot.irc, bot.channel, str(bot.state["quiz_iterator"]) + ". " + bot.state["quiz_current"]["question"])

def reply_pong(irc, text):
    for i in range(len(text.split())):
        if text.split()[i] == "PING":
            irc.send(bytes('PONG '+text.split()[i+1]+'\r\n', "UTF-8"))

def server_connect(irc, server, port, botnick):
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

def write_bot_state(bot):
    f = open("bot_state.txt", "w")
    f.write(str(bot.state["ragequits"])+"\n")
    f.write(bot.state["greeter-blacklist"]+"\n")
    f.close()

if __name__ == "__main__":
    main()
