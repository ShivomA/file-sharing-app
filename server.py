from flask import (
    Flask,
    request,
    url_for,
    session,
    redirect,
    render_template,
    send_from_directory
)

from flask_pymongo import PyMongo
from datetime import datetime
from hashlib import sha256
from werkzeug.utils import secure_filename
from bson import ObjectId
from Cfg import Config

import os
import random
import string


app = Flask(__name__)
app.secret_key = "121"
app.config["MONGO_URI"] = Config["URI"]
app.config['UPLOAD_FOLDER'] = Config["UploadLocation"]
mongo = PyMongo(app)

usersDatabase = mongo.db.users
tokensDatabase = mongo.db.userTokens
filesDatabase = mongo.db.files
fileDownloadsDatabase = mongo.db.fileDownloads


def get_random_string(length):
    letters = string.ascii_lowercase
    result_str = ''.join(random.choice(letters) for i in range(length))
    return result_str

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config["ALLOWED_EXTENSIONS"]

def UploadFile(file, filename):
    tokenRecord = tokensDatabase.find_one({"SessionHash": session["UserToken"]})
    random_string = get_random_string(random.randint(12, 15))
    saveName = filename.rsplit('.', 1)[0] + random_string + "." + filename.rsplit('.', 1)[1].lower()
    filePath = os.path.join(app.config['UPLOAD_FOLDER'], session["UserId"], saveName)
    fileType = filename.rsplit('.', 1)[1].lower()
    file.save(filePath)
    fileHash = sha256(file.read()).hexdigest()

    file.seek(0, os.SEEK_END)
    fileLength = file.tell()
    if fileLength > Config["MaximumUploadSize"]:
        session["Error"] = "File size is greater than " + str(Config["MaximumUploadSize"] / 1024 / 1024) + " MB"
        os.remove(filePath)
        return
    newUploadDataSize = usersDatabase.find_one({"_id": tokenRecord["UserId"]})["UploadDataSize"] + fileLength
    if newUploadDataSize >= Config["UploadSizePerUser"]:
        session["Error"] = "You have reached maximum storage space available per user"
        os.remove(filePath)
        return

    filesInfo = {
        "UserId": ObjectId(session["UserId"]),
        "OriginalFileName": file.filename,
        "FileName": saveName,
        "FileType": fileType,
        "FileHash": fileHash,
        "FileSize": fileLength,
        "FilePath": filePath,
        "IsActive": True,
        "CreatedAt": datetime.now()
    }
    filesDatabase.insert_one(filesInfo)

    usersDatabase.update_one({"_id": tokenRecord["UserId"]}, {"$set": {"UploadDataSize": newUploadDataSize}})
    session["Info"] = "File uploaded"

def GetFilesList():
    filesList = []
    if session["UserToken"] != "guest":
        files = filesDatabase.find({"UserId": ObjectId(session["UserId"]), "IsActive": True}).sort("CreatedAt", -1)
        for record in files:
            fileSize = record["FileSize"]
            units = ["B", "KB", "MB"]
            unit = units[0]
            for i in range(1, 3):
                if fileSize > 1024:
                    fileSize = round(fileSize / 1024, 1)
                    unit = units[i]
            fileList = [record["OriginalFileName"], str(fileSize) + unit,
                        record["CreatedAt"].date(), record["FileName"]]
            filesList.append(fileList)

    return filesList

def ShowInfo():
    info = ""
    if "Info" in session:
        info = session["Info"]
        session.pop("Info", None)
    return info

def ShowError():
    error = ""
    if "Error" in session:
        error = session["Error"]
        session.pop("Error", None)
    return error


# region Main

@app.route('/')
def Home():
    if not session.get("UserToken"):
        session["Error"] = "Please login to access the home page"
        return redirect(url_for("Login"))

    if not tokensDatabase.find_one({"SessionHash": session["UserToken"]}) and session["UserToken"] != "guest":
        session.pop("UserToken", None)
        session.pop("Username", None)
        session["Error"] = "Please login again to access the home page"
        return redirect(url_for("Login"))

    return render_template("home.html",
                           name=session["Username"], filesInfo=GetFilesList(),
                           error=ShowError(), info=ShowInfo())


@app.route('/updateData', methods=["POST"])
def updateData():
    if session["UserToken"] == "guest":
        session["Error"] = "You are using guest login. Please Login as user to use this app's cool feature"
        return redirect(url_for("Home"))

    if "file" in request.files:
        file = request.files["file"]
        filename = secure_filename(file.filename)
        if filename == "":
            session["Error"] = "Please choose some file to upload"
            return redirect(url_for("Home"))

        if not allowed_file(file.filename):
            session["Error"] = "Please select files among given extensions" + str(Config["ALLOWED_EXTENSIONS"])
            return redirect(url_for("Home"))

        UploadFile(file, filename)

        return redirect(url_for("Home"))

    if "delete" in request.form:
        data = {"UserId": ObjectId(session["UserId"]), "FileName": request.form["delete"], "IsActive": True}
        filesDatabase.update_one(data, {"$set": {"IsActive": False}})
        return redirect(url_for("Home"))

    if "share" in request.form:
        return "Share is not available yet."


@app.route('/show/<filename>', methods=["POST"])
def show(filename):
    filePath = os.path.join(app.config['UPLOAD_FOLDER'], session["UserId"])
    return send_from_directory(filePath, filename)
# endregion


# region Login/Logout

@app.route('/login/')
def Login():
    if session.get("UserToken"):
        return redirect(url_for("Home"))
    else:
        return render_template("login.html", info=ShowInfo(), error=ShowError())


@app.route('/checkLogin', methods=["POST"])
def CheckData():
    email = request.form["email"].lower()
    password = request.form["password"]

    if len(email) == 0 and len(password) == 0:
        session["UserToken"] = "guest"
        session["Username"] = "Guest"
        return redirect(url_for("Home"))

    userData = usersDatabase.find_one({"Email": email})

    if userData is None:
        session["Error"] = "Email not found! Please signup!"
        return redirect(url_for("Login"))

    password = sha256(password.encode("utf-8")).hexdigest()
    if userData["Password"] == password:
        random_string = get_random_string(random.randint(8, 12))
        randomSessionHash = sha256(random_string.encode("utf-8")).hexdigest()
        userToken = {
            "UserId": userData["_id"],
            "Username": userData["Name"],
            "SessionHash": randomSessionHash,
            "CreatedAt": datetime.now()
        }
        tokensDatabase.insert_one(userToken)
        session["UserId"] = str(userData["_id"])
        session["Username"] = userData["Name"]
        session["UserToken"] = randomSessionHash
        return redirect(url_for("Home"))
    else:
        session["Error"] = "Password Incorrect!"
        return redirect(url_for("Login"))


@app.route('/logout')
def Logout():
    if not session.get("UserToken"):
        session["Error"] = "User already logged out"
        return redirect(url_for("Login"))
    tokenRecord = tokensDatabase.find_one({"SessionHash": session["UserToken"]})
    if tokenRecord is not None:
        usersDatabase.update_one({"_id": tokenRecord["UserId"]}, {"$set": {"LastLoginDate": datetime.now()}})
        tokensDatabase.delete_one(tokenRecord)
    session.pop("UserToken", None)
    session.pop("Username", None)
    session["Info"] = "Logout successful"
    return redirect(url_for("Login"))
# endregion


# region SignUp

@app.route('/signup/')
def Signup():
    return render_template("signup.html", error=ShowError(), info=ShowInfo())


@app.route('/checkSignup', methods=["POST"])
def GetData():
    email = request.form["email"].lower()
    name = request.form["name"]
    password = request.form["password"]
    password2 = request.form["password2"]

    if len(email) == 0:
        session["Error"] = "Please Enter Valid Email"
        return redirect(url_for("Signup"))
    elif password != password2:
        session["Error"] = "Please enter same password in both field"
        return redirect(url_for("Signup"))
    elif len(password) <= 2:
        session["Error"] = "Please keep password length greater than 2"
        return redirect(url_for("Signup"))

    if usersDatabase.count_documents({"Email": email}) != 0:
        session["Error"] = email + " already register!"
        return redirect(url_for("Signup"))

    password = sha256(password.encode("utf-8")).hexdigest()
    Info = {
        "Email": email,
        "Password": password,
        "Name": name,
        "LastLoginDate": None,
        "UploadDataSize": 0,
        "CreatedAt": datetime.now(),
        "UpdatedAt": datetime.now()
    }

    usersDatabase.insert_one(Info)

    userId = str(usersDatabase.find_one({"Email": email})["_id"])
    path = os.path.join(app.config['UPLOAD_FOLDER'], userId)
    os.mkdir(path)

    session["Info"] = "Signup successful"

    return redirect(url_for("Login"))
# endregion
