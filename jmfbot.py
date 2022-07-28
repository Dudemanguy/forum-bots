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
    names = {}
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
        "quiz_channel": "",
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

class irc_message():
    args = ""
    channel = ""
    command = ""
    mode = ""
    nickchange = ""
    trigger_action = False
    trigger_command = False
    text = ""
    user = ""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--botnick", type=str, default="jmfbot", nargs='?', const=1, help="bot nickname")
    parser.add_argument("--botpass", type=str, default= "", nargs='?', const=1, help="bot password")
    parser.add_argument("--channel", type=str, default=["#forcesofsteel","#jpmetal","#revelationofdoom"], nargs='?', const=1, help="channel to join")
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

    if os.path.isfile("bot_state.txt"):
        f = open("bot_state.txt", "r")
        lines = f.readlines()
        bot.state["ragequits"] = int(lines[0].strip())
        bot.state["greeter-blacklist"] = lines[1].strip()
        f.close();

    old_full = []
    bot.irc = socket.socket()
    if bot.state["ssl"]:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.load_default_certs()
        bot.irc = context.wrap_socket(bot.irc)
    server_connect(bot.irc, bot.server, bot.port, bot.botnick)

    bot.poller = select.poll()
    bot.poller.register(bot.irc, select.POLLIN)

    bot.state["wakeup_time"] = time.time() + bot.state["sleep_interval"]
    timeout = bot.state["sleep_interval"]*1000

    initialized = False
    first_join = True
    bot.irc.setblocking(0)

    while True:
        current_time = time.time()
        if current_time < bot.state["wakeup_time"]:
            timeout = (bot.state["wakeup_time"] - current_time)*1000
        bot.poller.poll(timeout)
        text = get_response(bot.irc)

        if not initialized and text.find("please choose a different nick") != -1:
            identify_name(bot)
            channel_join(bot)

        if not initialized and text.find(":") != -1:
            check_names_response(bot, text)

        if not initialized and text.find('+v') != -1:
            initialized = True

        if text[:4] == "PING":
            pong_domain = text.split(":")[1]
            bot.irc.send(bytes('PONG ' + pong_domain + '\r\n', "UTF-8"))
            continue

        message = irc_message()

        if initialized:
            create_message(bot, message, text)

        if message.trigger_command:
            execute_command(bot, message)

        if message.trigger_action:
            execute_action(bot, message)

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
                    msg_send(bot.irc, bot.state["quiz_channel"], "The correct answer was " + bot.state["quiz_current"]["answer"] + ".")
                    if bot.state["quiz_iterator"] == bot.state["quiz_size"]:
                        bot.state["quiz_state"] = False
                        bot.state["sleep_interval"] = 60
                        if bot.state["quiz_score"] == {}:
                            msg_send(bot.irc, bot.state["quiz_channel"], "Quiz finished. Wow, no one won. You guys suck.")
                        else:
                            winner = max(bot.state["quiz_score"], key=bot.state["quiz_score"].get)
                            score = bot.state["quiz_score"][winner]
                            msg_send(bot.irc, bot.state["quiz_channel"], "Quiz finished. Winner is " + winner + " with a score of " + str(score) + ".")
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

        if time.time() >= bot.state["wakeup_time"]:
            soup = get_html_mechanize(bot, bot.searchurl)
            if soup == -1:
                continue
            full = update_info(bot, soup)
            for i in range(0, len(full)):
                if not exists_in_old(full[i], old_full) and not first_join:
                    msg_send(bot.irc, "#jpmetal", "["+bot.botnick+"] "+full[i][0]+" made a new post in thread: "+full[i][1]+" ("+full[i][2]+") -- "+full[i][3])
            if first_join:
                first_join = False
            old_full = full
            bot.state["wakeup_time"] = time.time() + bot.state["sleep_interval"]

    return 0

def bblquit(bot, message):
    chance = random.randint(1, 100)
    if chance > 55:
        msg_send(bot.irc, message.channel, "fuck off "+message.user)
    else:
        msg_send(bot.irc, message.channel, "bbl "+message.user)

def channel_join(bot):
    for channel in bot.channel:
        bot.irc.send(bytes("JOIN " + channel + "\n", "UTF-8"))
        msg_send(bot.irc, channel, "hi")

def check_names_response(bot, text):
    if len(text.split(":")) < 3:
        return
    server_text = text.split(":")[1]
    for channel in bot.channel:
        if server_text.find(bot.botnick + " @ " + channel) != -1 or server_text.find(bot.botnick + " * " + channel) != -1:
            bot.names[channel] = text.split(":")[2].split()

def check_for_quiz_answer(bot, message):
    if not bot.state["quiz_state"]:
        return
    text = " ".join(message.text)
    if bot.state["quiz_current"]["answer"].lower() in text.lower():
        msg_send(bot.irc, message.channel, 
            "Winner: " + message.user + "; Answer: "+bot.state["quiz_current"]["answer"])
        if message.user in bot.state["quiz_score"]:
            bot.state["quiz_score"][message.user] += 1
        else:
            bot.state["quiz_score"][message.user] = 1
        bot.state["quiz_current"]["hint_level"] = 3
        bot.state["wakeup_time"] = time.time()

def check_for_url(bot, message):
    if " ".join(message.text).find("http") != -1 or re.search("www", " ".join(message.text)):
        for substring in message.text:
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
                if soup.find("title") and soup.find("title").contents:
                    msg_send(bot.irc, message.channel, "[Title] "+soup.find("title").contents[0].strip())

def create_message(bot, message, text):
    if text == "":
        return
    text_split = text.split()
    if text.find("!") == -1:
        return
    message.user = text_split[0].split("!")[0][1:]
    match text_split[1]:
        case "JOIN":
            message.channel = text_split[2][1:]
            user_entry(bot, message)
            return
        case "MODE":
            if len(text_split) < 5:
                return
            message.channel = text_split[2]
            message.mode = text_split[3]
            message.user = text_split[4]
            user_mode(bot, message)
            return
        case "NICK":
            message.nickchange = text_split[2][1:]
            nick_change(bot, message)
            return
        case "PART":
            message.channel = text_split[2]
            user_part(bot, message)
            return
        case "QUIT":
            user_quit(bot, message)
    if len(text_split) < 4:
        return
    message.channel = text_split[2]
    message.text = text_split[3:]
    if message.channel == bot.botnick and text_split[1] == "PRIVMSG":
        message.trigger_command = True
        if len(message.text) >= 2:
            message.command = message.text[0][1:]
            message.channel = message.text[1]
        if len(message.text) >= 3:
            message.args = message.text[2:]
        return
    if message.text[0] == ":." + bot.botnick:
        message.trigger_command = True
        if len(message.text) >= 2:
            message.command = message.text[1]
        if len(message.text) >= 3:
            message.args = message.text[2:]
        return
    message.text[0] = message.text[0][1:]
    message.trigger_action = True

def execute_action(bot, message):
    match message.text[0].lower():
        case "bbl":
            bblquit(bot, message)
            return
        case "jambo":
            jambo(bot, message)
            return
    check_for_quiz_answer(bot, message)
    check_for_url(bot, message)

def execute_command(bot, message):
    match message.command:
        case "dice":
            execute_dice_command(bot, message)
        case "echo":
            execute_echo_command(bot, message)
        case "" | "help":
            execute_help_command(bot, message)
        case "kill":
            execute_kill_command(bot, message)
        case "me":
            execute_me_command(bot, message)
        case "pull":
            execute_pull_command(bot, message)
        case "quiz":
            execute_quiz_command(bot, message)
        case "reboot":
            execute_reboot_command(bot, message)
        case "set":
            execute_set_command(bot, message)
        case "show":
            execute_show_command(bot, message)
        case "thread":
            execute_thread_command(bot, message)

def execute_dice_command(bot, message):
    if message.args == "":
        size = 10
    elif message.args[0].isdigit():
        size = int(message.args[0])
    else:
        return
    roll = random.randint(1, size)
    msg_send(bot.irc, message.channel, str(roll))

def execute_echo_command(bot, message):
    msg_send(bot.irc, message.channel, " ".join(message.args))

def execute_help_command(bot, message):
    match message.args:
        case "":
            msg_send(bot.irc, message.channel, "Usage: execute the bot with either ."+bot.botnick+" or /msg "+bot.botnick+" #channelname followed by [command] [arguments]")
            msg_send(bot.irc, message.channel, "Try '[execute] help [command]' for more details about a particular command")
            msg_send(bot.irc, message.channel, "Available commands: dice, echo, help, kill, me, pull, quiz, reboot, set, show, thread")
        case ["dice"]:
            msg_send(bot.irc, message.channel, "dice [size (optional)] -- roll a dice with a certain size (default 10)")
        case ["echo"]:
            msg_send(bot.irc, message.channel, "echo [message] -- tell the bot echo back a message")
        case ["help"]:
            msg_send(bot.irc, message.channel, "help [command (optional)] -- display detailed help output for a particular command")
        case ["kill"]:
            msg_send(bot.irc, message.channel, "kill [timeout (optional)] -- kill the bot with an optional timeout (channel op only)")
        case ["me"]:
            msg_send(bot.irc, message.channel, "me [message] -- tell the bot to send a message with /me")
        case ["pull"]:
            msg_send(bot.irc, message.channel, "pull -- pull the latest changes from git (channel op only)")
        case ["quiz"]:
            msg_send(bot.irc, message.channel, "quiz [file] [number (optional)] -- start a locally stored quiz with the bot with an optional number of questions (default 10)")
        case ["reboot"]:
            msg_send(bot.irc, message.channel, "reboot [timeout (optional)] reboot the bot with an optional timeout (channel op only)")
        case ["set"]:
            msg_send(bot.irc, message.channel, "set [property] [value] -- set one of the bot's properties to a particular value (channel op only)")
        case ["show"]:
            msg_send(bot.irc, message.channel, "show [property] -- show the value of one of the bot's properties")
        case ["thread"]:
            msg_send(bot.irc, message.channel, "thread [random/integer (optional)] -- get a random thread (default) or optionally specifiy one with an integer")

def execute_kill_command(bot, message):
    if is_op(bot, message):
        if message.args != "" and only_numbers(message.args[0]):
            bot.state["wakeup_time"] = time.time() + int(message.args[0])
            msg_send(bot.irc, message.channel, "Dying in "+message.args[0]+" seconds")
        elif message.args != "" and not only_numbers(message.args[0]):
            msg_send(bot.irc, message.channel, "Error: timeout must be an integer value")
            return
        else:
            bot.state["wakeup_time"] = time.time()
        bot.state["kill"] = True
    else:
        msg_send(bot.irc, message.channel, "Only channel ops can kill me.")

def execute_me_command(bot, message):
    msg_me(bot.irc, message.channel, " ".join(message.args))

def execute_pull_command(bot, message):
    if not is_op(bot, message):
        msg_send(bot.irc, message.channel, "Only channel ops can use the pull command.")
        return
    msg_send(bot.irc, message.channel, "Pulling the latest changes from git")
    os.system("git pull")

def execute_quiz_command(bot, message):
    if message.args == "":
        return
    if len(args) > 1 and message.args[1].isdigit():
        size = int(message.args[1])
    else:
        size = 10
    quiz_file = message.args[0] + ".json"
    if os.path.isfile(quiz_file):
        with open(quiz_file) as f:
            bot.state["quiz"] = json.load(f, encoding="utf-8")
        if size > len(bot.state["quiz"]):
            size = len(bot.state["quiz"])
        msg_send(bot.irc, message.channel, "Starting quiz " + message.args[0] + ".")
        bot.state["quiz_channel"] = message.channel
        bot.state["quiz_size"] = size
        bot.state["quiz_state"] = True
        bot.state["sleep_interval"] = 10
        bot.state["wakeup_time"] = time.time() + bot.state["sleep_interval"]
        quiz_new_question(bot)
    else:
        msg_send(bot.irc, message.channel, quiz_file + " was not found!")

def execute_reboot_command(bot, message):
    if is_op(bot, message):
        if message.args != "" and only_numbers(message.args[0]):
            bot.state["wakeup_time"] = time.time() + int(message.args[0])
            msg_send(bot.irc, message.channel, "Rebooting in "+message.args[0]+" seconds")
        elif message.args != "" and not only_numbers(message.args[0]):
            msg_send(bot.irc, message.channel, "Error: timeout must be an integer value")
            return
        else:
            bot.state["wakeup_time"] = time.time()
        bot.state["reboot"] = True
    else:
        msg_send(bot.irc, message.channel, "Only channel ops can reboot me.")

def execute_set_command(bot, message):
    if not is_op(bot, message):
        msg_send(bot.irc, message.channel, "Only channel ops can use the set command.")
        return
    if message.args == "":
        return
    if message.args[0] == "greeter":
        if message.args[1] == "on":
            bot.state["greeter"] = True
            msg_send(bot.irc, message.channel, "User greeter turned on")
        elif message.args[1] == "off":
            bot.state["greeter"] = False
            msg_send(bot.irc, message.channel, "User greeter turned off")
    if message.args[0] == "greeter-blacklist" and len(message.args) == 2:
        bot.state["greeter-blacklist"] = message.args[1]
        msg_send(bot.irc, message.channel, "User greeter blacklist set to '" + bot.state["greeter-blacklist"] + "'.")
    elif message.args[0] == "op-only":
        if message.args[1] == "on":
            bot.state["op-only"] = True
            msg_send(bot.irc, message.channel, "Only listening to commands from channel ops")
        elif message.args[1] == "off":
            bot.state["op-only"] = False
            msg_send(bot.irc, message.channel, "Listening to commands from all users")
    elif message.args[0] == "ragequits":
        if only_numbers(message.args[1]):
            bot.state["ragequits"] = int(message.args[1])
            msg_send(bot.irc, message.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
        else:
            msg_send(bot.irc, message.channel, "Error: ragequits can only be set to an integer value")

def execute_show_command(bot, message):
    if message.args == "":
        msg_send(bot.irc, message.channel, "greeter -- greet users on entry (boolean: on/off)")
        msg_send(bot.irc, message.channel, "greeter-blacklist -- exclude users from greeter (string: user1,user2,user3...)")
        msg_send(bot.irc, message.channel, "op-only -- only listen to commands from channel ops (boolean: on/off)")
        msg_send(bot.irc, message.channel, "ragequits -- ragequit counter (integer)")
    elif message.args[0] == "greeter":
        if bot.state["greeter"]:
            msg_send(bot.irc, message.channel, "User greeter turned on")
        else:
            msg_send(bot.irc, message.channel, "User greeter turned off")
    elif message.args[0] == "greeter-blacklist":
        msg_send(bot.irc, message.channel, "The greeter blacklist is '" + bot.state["greeter-blacklist"]+"'.")
    elif message.args[0] == "op-only":
        if bot.state["op-only"]:
            msg_send(bot.irc, message.channel, "op-only is turned on")
        else:
            msg_send(bot.irc, message.channel, "op-only is turned off")
    elif message.args[0] == "ragequits":
        msg_send(bot.irc, message.channel, "The ragequit counter is at "+str(bot.state["ragequits"]))

def execute_thread_command(bot, message):
    thread_url = ""
    thread_title = ""
    if message.args == "" or message.args[0] == "random":
        # add this mysterious constant that exists for unknown reasons but whatever
        thread_count = 4643
        if thread_count > 0:
            tid = random.randint(1, thread_count)
            thread_url = bot.baseurl+str(tid)
            thread_title = get_thread_title(bot, thread_url)
    elif message.args[0].isdigit():
        thread_url = bot.baseurl+args[0]
        thread_title = get_thread_title(bot, thread_url)
    if thread_title != "" and thread_url != "":
        msg_send(bot.irc, message.channel, thread_title+" -- "+thread_url)

def exists_in_old(item, old_full):
    for i in range(0, len(old_full)):
        if item == old_full[i]:
            return True
    return False

def get_channel(text):
    if text.find(" ") != -1:
        return text.split()[2]

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
    str_split = text.split()
    channel = str_split[4]
    bot.names[channel] = str_split[5:]

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

def identify_name(bot):
    bot.irc.send(bytes("PRIVMSG NickServ@services.rizon.net :IDENTIFY "+bot.botpass+"\r\n", "UTF-8"))

def is_op(bot, message):
    for name in bot.names[message.channel]:
        if name[0] == "@" and message.user == name[1:]:
            return True
    return False

def is_voice(bot, message):
    for i in bot.names[message.channel]:
        if i[0] == "+" and message == i[1:]:
            return True
    return False

def jambo(bot, message):
    if message.user == "djindy":
        msg_send(bot.irc, message.channel, "mambo")

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

def nick_change(bot, message):
    for channel in bot.channel:
        for name in bot.names[channel]:
            if name == message.user:
                bot.names[bot.channel].remove(name)
                bot.names[bot.channel].append(message.nickchange)
            if name[1:] == message.user:
                bot.names[bot.channel].remove(name)
                bot.names[bot.channel].append(name[1] + message.nickchange)

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
    msg_send(bot.irc, bot.state["quiz_channel"], "Hint: "+hint)

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
    msg_send(bot.irc, bot.state["quiz_channel"], str(bot.state["quiz_iterator"]) + ". " + bot.state["quiz_current"]["question"])

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

def user_entry(bot, message):
    bot.names[message.channel].append(message.user)
    blacklist = bot.state["greeter-blacklist"].split(",")
    if bot.state["greeter"] and not message.user in blacklist:
        msg_send(bot.irc, message.channel, "hi "+message.user)

def user_part(bot, message):
    if message.user.lower() == "jeckidy":
        bot.state["ragequits"] += 1
        msg_send(bot.irc, message.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
        write_bot_state(bot)

    for name in bot.names[message.channel]:
        if name == message.user or name[1:] == message.user:
            bot.names[message.channel].remove(name)

def user_quit(bot, message):
    if message.user.lower() == "jeckidy":
        bot.state["ragequits"] += 1
        msg_send(bot.irc, message.channel, "Ragequit counter updated to "+str(bot.state["ragequits"]))
        write_bot_state(bot)

    for channel in bot.channel:
        for name in bot.names[channel]:
            if name == message.user or name[1:] == message.user:
                bot.names[channel].remove(name)

def user_mode(bot, message):
    if message.mode == "+v":
        bot.names[message.channel].remove(message.user)
        bot.names[message.channel].append("+"+message.user)
    if message.mode == "+o":
        bot.names[message.channel].remove(message.user)
        bot.names[message.channel].append("@"+message.user)

def write_bot_state(bot):
    f = open("bot_state.txt", "w")
    f.write(str(bot.state["ragequits"])+"\n")
    f.write(bot.state["greeter-blacklist"]+"\n")
    f.close()

if __name__ == "__main__":
    main()
