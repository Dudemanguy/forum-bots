import getpass
import http.cookiejar
import mechanize
import re
import socket
import ssl
import time
from bs4 import BeautifulSoup

def channel_join(irc, channel):
    time.sleep(1)
    irc.send(bytes("JOIN " + channel + "\n", "UTF-8"))
    return True
 
def msg_send(irc, channel, msg):
    irc.send(bytes("PRIVMSG " + channel + " :" + msg + "\n", "UTF-8"))

def get_response(irc):
    time.sleep(1)
    resp = irc.recv(4096).decode("UTF-8")
    return resp
 
def server_connect(irc, server, port, botnick):
    print("Connecting to: " + server)
    irc.connect((server, port))
    irc.send(bytes("USER " + botnick + " " + botnick +" " + botnick + " :python\n", "UTF-8"))
    irc.send(bytes("NICK " + botnick + "\n", "UTF-8"))
    time.sleep(5)

def execute_command(irc, channel, substring, user):
    if substring[:5] == "echo ":
        arguments = substring.split("echo ")[1]
        msg_send(irc, channel, arguments)
        return 0
    if substring[:4] == "quit":
        irc.send(bytes("NAMES " + channel + "\n", "UTF-8"))
        names = get_response(irc)
        names = names.split()
        for i in names:
            if i[0] == "@" and user == i[1:]:
                msg_send(irc, channel, "bbl")
                irc.shutdown(2)
                irc.close()
                return 1
        msg_send(irc, channel, "Only channel ops can kill me.")
        return 0

def check_for_command(irc, channel, text):
    if text.find('.JMFbot ') != -1:
        user = text.split("~")[0][1:]
        user = user[:len(user)-1]
        substring = text.split(".JMFbot ")[1]
        ret = execute_command(irc, channel, substring, user)
        return ret

def identify_name(irc, text, botpass):
    if text.find('PING') != -1:
        irc.send(bytes("PRIVMSG NickServ@services.rizon.net :IDENTIFY "+botpass+"\r\n", "UTF-8"))
        return True
    return False

def reply_pong(irc, text):
    if text.find('PING') != -1:                      
        for i in range(len(text.split())):
            if text.split()[i] == "PING":
                irc.send(bytes('PONG '+text.split()[i+1]+'\r\n', "UTF-8"))

def get_new_html():
    searchurl = "https://japanesemetalforum.com/search.php?action=getdaily"
    posts = br.open(searchurl).read()
    soup = BeautifulSoup(posts, "html.parser")
    return soup

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

def exists_in_old(item, old_full):
    for i in range(0, len(old_full)):
        if item == old_full[i]:
            return True
    return False

baseurl = "https://jpmetal.org/showthread.php?tid="
loginurl = "https://japanesemetalforum.com/member.php?action=login"
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
in_channel = False
first_join = True
identified = False
init_server_message = False
old_full = []
old_time = 0

while True:
    text = get_response(irc)
    print(text)
    elapsed_time = time.time() - old_time

    reply_pong(irc, text)

    if not identified:
        identified = identify_name(irc, text, botpass)

    if not init_server_message:
        if text.find('+r') != -1:                      
            init_server_message = True
        continue

    if not in_channel and identified and init_server_message:
        in_channel = channel_join(irc, channel)

    ret = check_for_command(irc, channel, text)
    if ret == 1:
        break

    if in_channel and elapsed_time > 60:
        soup = get_new_html()
        full = update_info(soup)
        for i in range(0, len(full)):
            if not exists_in_old(full[i], old_full) and not first_join:
                msg_send(irc, channel, "[JMFbot] "+full[i][0]+" made a new post in thread: "+full[i][1]+" ("+full[i][2]+") -- "+full[i][3])
                time.sleep(1)
        if first_join:
            msg_send(irc, channel, "hi")
            first_join = False
        old_full = full
        old_time = time.time()

    time.sleep(5)
