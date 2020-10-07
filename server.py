from flask import (
    Flask,
    request,
    url_for,
    session,
    redirect,
    send_file,
    render_template,
    send_from_directory
)

from Cfg import Config
from bson import ObjectId
from hashlib import sha256
from datetime import datetime
from flask_pymongo import PyMongo
from werkzeug.utils import secure_filename

import os
import string
import random


# region Configurations

app = Flask(__name__)
app.secret_key = "121"
app.config["MONGO_URI"] = Config["URI"]
app.config['UPLOAD_FOLDER'] = Config["UploadLocation"]
timeout = Config["PyMongoTimeOut"]
mongo = PyMongo(app, socketTimeoutMS=timeout, connectTimeoutMS=timeout, serverSelectionTimeoutMS=timeout)

usersDatabase = mongo.db.users
tokensDatabase = mongo.db.userTokens
filesDatabase = mongo.db.files
sharableFilesDatabase = mongo.db.sharableFiles
fileDownloadsDatabase = mongo.db.fileDownloads
# endregion


# region Functions

def get_random_string(length):
    letters = string.ascii_lowercase
    result_str = ''.join(random.choice(letters) for _ in range(length))
    return result_str

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config["ALLOWED_EXTENSIONS"]

def UploadFile(file, filename):
    try:
        tokenRecord = tokensDatabase.find_one({"SessionHash": session["UserToken"]})
    except:
        session["Error"] = "File cannot be uploaded! Please check the connection."
        tokenRecord = None

    if tokenRecord is None:
        return

    file.seek(0, os.SEEK_END)
    fileLength = file.tell()
    if fileLength > Config["MaximumUploadSize"]:
        session["Error"] = "File size is greater than " + str(Config["MaximumUploadSize"] / 1024 / 1024) + " MB"
        return
    try:
        newUploadedDataSize = usersDatabase.find_one({"_id": tokenRecord["UserId"]})["UploadedDataSize"] + fileLength
        if newUploadedDataSize >= Config["UploadSizePerUser"]:
            session["Error"] = "You have reached maximum storage space available per user"
            return
    except:
        session["Error"] = "File cannot be uploaded! Please check the connection."
        return

    file.seek(0, 0)
    random_string = get_random_string(random.randint(12, 15))
    saveName = filename.rsplit('.', 1)[0] + random_string + "." + filename.rsplit('.', 1)[1].lower()
    filePath = os.path.join(app.config['UPLOAD_FOLDER'], session["UserId"], saveName)
    fileType = filename.rsplit('.', 1)[1].lower()
    file.save(filePath)

    file.seek(0, 0)
    fileHash = sha256(file.read()).hexdigest()

    filesInfo = {
        "UserId": ObjectId(session["UserId"]),
        "OriginalFileName": file.filename,
        "FileName": saveName,
        "FileType": fileType,
        "FileHash": fileHash,
        "FilePath": filePath,
        "FileSize": fileLength,
        "IsActive": True,
        "UploadedAt": datetime.now()
    }

    try:
        filesDatabase.insert_one(filesInfo)
        usersDatabase.update_one({"_id": tokenRecord["UserId"]}, {"$set": {"UploadedDataSize": newUploadedDataSize}})
        session["Info"] = "File uploaded"
    except:
        session["Error"] = "File cannot be uploaded! Please check the connection."

def GetFilesList():
    filesList = []
    if session["UserToken"] != "guest":
        try:
            files = filesDatabase.find({"UserId": ObjectId(session["UserId"]), "IsActive": True}).sort("UploadedAt", -1)
            for record in files:
                fileSize = record["FileSize"]
                units = ["B", "KB", "MB"]
                unit = units[0]
                for i in range(1, 3):
                    if fileSize > 1024:
                        fileSize = round(fileSize / 1024, 1)
                        unit = units[i]
                fileList = [record["OriginalFileName"], str(fileSize) + unit,
                            record["UploadedAt"].date(), record["FileName"],
                            str(record["UserId"])]
                filesList.append(fileList)
        except:
            return filesList

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
# endregion


# region Main

@app.route('/')
def Home():
    if not session.get("UserToken"):
        session["Error"] = "Please login to access the home page"
        return redirect(url_for("Login"))

    try:
        if not tokensDatabase.find_one({"SessionHash": session["UserToken"]}) and session["UserToken"] != "guest":
            session.pop("UserToken", None)
            session.pop("Username", None)
            session["Error"] = "You are logged out! Please login again to access the home page"
            return redirect(url_for("Login"))
    except:
        if "Error" not in session:
            session["Error"] = "Cannot connect to the host! Please check the connection."

    if "Download" in session:
        downloadInfo = session["Download"]
        session.pop("Download", None)
        if session["UserToken"] != "guest":
            return redirect(url_for("Download", userId=downloadInfo[0], fileName=downloadInfo[1]))

    return render_template("home.html", inx=-1,
                           name=session["Username"], filesInfo=GetFilesList(),
                           error=ShowError(), info=ShowInfo())


@app.route('/updateData', methods=["POST"])
def UpdateData():
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
        try:
            data = {"UserId": ObjectId(session["UserId"]), "FileName": request.form["delete"], "IsActive": True}
            filesDatabase.update_one(data, {"$set": {"IsActive": False}})
        except:
            session["Error"] = "Unable to delete file! Please check connection."
        return redirect(url_for("Home"))


@app.route('/view/<filename>', methods=["POST"])
def View(filename):
    filePath = os.path.join(app.config['UPLOAD_FOLDER'], session["UserId"])
    return send_from_directory(filePath, filename)


@app.route('/share/<index>')
def Share(index):
    if not session.get("UserToken"):
        session["Error"] = "Please login to access the home page"
        return redirect(url_for("Login"))

    try:
        if not tokensDatabase.find_one({"SessionHash": session["UserToken"]}) and session["UserToken"] != "guest":
            session.pop("UserToken", None)
            session.pop("Username", None)
            session["Error"] = "You are logged out! Please login again to access the home page"
            return redirect(url_for("Login"))
    except:
        if "Error" not in session:
            session["Error"] = "Cannot connect to the host! Please check the connection."

    return render_template("home.html", inx=int(index),
                           name=session["Username"], filesInfo=GetFilesList(),
                           error=ShowError(), info=ShowInfo())


@app.route('/createPermalink/<userId>/<fileName>', methods=["POST"])
def CreatePermalink(userId, fileName):
    filePath = os.path.join(app.config['UPLOAD_FOLDER'], userId)
    file = os.path.join(filePath, fileName)
    try:
        if not sharableFilesDatabase.find_one({"Link": file}):
            sharableFilesDatabase.insert_one({"Link": file, "SharedBy": session["Username"]})
            session["Info"] = "This link is now public and can be used to download given file."
        else:
            session["Info"] = "This link is already public."
    except:
        session["Error"] = "Unable to make link public! Please check connection."
    return redirect(url_for("Home"))


@app.route('/share/download/<userId>/<fileName>', methods=["GET", "POST"])
def Download(userId, fileName):
    filePath = os.path.join(app.config['UPLOAD_FOLDER'], userId)
    file = os.path.join(filePath, fileName)

    if "UserToken" not in session or session["UserToken"] == "guest":
        session["Info"] = "Please login to download the file!"
        session["Download"] = [userId, fileName]
        return redirect(url_for("Login"))

    try:
        if sharableFilesDatabase.find_one({"Link": file}):
            fileInfo = filesDatabase.find_one({"FileName": fileName})
            downloadInfo = {
                "FileId": fileInfo["_id"],
                "UserId": ObjectId(session["UserId"]),
                "FileName": fileInfo["OriginalFileName"],
                "DownloadedBy": session["Username"],
                "DownloadedAt": datetime.now()
            }
            fileDownloadsDatabase.insert_one(downloadInfo)
            return send_file(file, as_attachment=True)

        session["Error"] = "Invalid download link! or The link is not public!"
    except:
        session["Error"] = "Unable to download! Please check connection."

    return redirect(url_for("Home"))
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
    if session.get("UserToken"):
        session["Info"] = "You are already Logged In!"
        return redirect(url_for("Home"))

    email = request.form["email"].lower()
    password = request.form["password"]

    if len(email) == 0 and len(password) == 0:
        session["UserToken"] = "guest"
        session["Username"] = "Guest"
        return redirect(url_for("Home"))

    try:
        userData = usersDatabase.find_one({"Email": email})
    except:
        session["Error"] = "Cannot connect to the host! Please check the connection."
        return redirect(url_for("Login"))

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
        try:
            tokensDatabase.insert_one(userToken)
            session["UserId"] = str(userData["_id"])
            session["Username"] = userData["Name"]
            session["UserToken"] = randomSessionHash
        except:
            session["Error"] = "Cannot connect to the host! Please check the connection."
            return redirect(url_for("Login"))

        return redirect(url_for("Home"))
    else:
        session["Error"] = "Password Incorrect!"
        return redirect(url_for("Login"))


@app.route('/logout')
def Logout():
    if not session.get("UserToken"):
        session["Error"] = "User already logged out"
        return redirect(url_for("Login"))

    try:
        tokenRecord = tokensDatabase.find_one({"SessionHash": session["UserToken"]})
        if tokenRecord is not None:
            usersDatabase.update_one({"_id": tokenRecord["UserId"]}, {"$set": {"LastLoginDate": datetime.now()}})
            tokensDatabase.delete_one(tokenRecord)
        session.pop("UserToken", None)
        session.pop("Username", None)
        session["Info"] = "Logout successful"
    except:
        session["Error"] = "Cannot connect to the host! Logout Unsuccessful! Please check the connection."
        return redirect(url_for("Home"))

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

    try:
        if usersDatabase.count_documents({"Email": email}) != 0:
            session["Error"] = email + " is already register!"
            return redirect(url_for("Signup"))
    except:
        session["Error"] = "Cannot connect to the host! Please check the connection."
        return redirect(url_for("Signup"))

    password = sha256(password.encode("utf-8")).hexdigest()
    Info = {
        "Email": email,
        "Password": password,
        "Name": name,
        "UploadedDataSize": 0,
        "LastLoginDate": None,
        "CreatedAt": datetime.now(),
        "UpdatedAt": datetime.now()
    }

    try:
        usersDatabase.insert_one(Info)
        userId = str(usersDatabase.find_one({"Email": email})["_id"])

        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
        path = os.path.join(app.config['UPLOAD_FOLDER'], userId)
        os.mkdir(path)
        session["Info"] = "Signup successful"
    except:
        session["Error"] = "Cannot connect to the host! Please check the connection."
        return redirect(url_for("Signup"))

    return redirect(url_for("Login"))
# endregion

if __name__ == "__main__":
    app.run(port=5000, debug=True)
