from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_CTBAS(object):
    def setupUi(self, CTBAS):
        CTBAS.setObjectName("CTBAS")
        CTBAS.resize(1200, 927)
        self.centralwidget = QtWidgets.QWidget(CTBAS)
        self.centralwidget.setObjectName("centralwidget")

        self.horizontalLayout = QtWidgets.QHBoxLayout(self.centralwidget)
        self.horizontalLayout.setObjectName("horizontalLayout")

        self.groupBox = QtWidgets.QGroupBox(self.centralwidget)
        self.groupBox.setObjectName("groupBox")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.groupBox)
        self.verticalLayout.setObjectName("verticalLayout")

        self.textEdit = QtWidgets.QTextEdit(self.groupBox)
        self.textEdit.setReadOnly(True)
        self.textEdit.setObjectName("textEdit")
        self.verticalLayout.addWidget(self.textEdit)

        self.pushButton = QtWidgets.QPushButton(self.groupBox)
        self.pushButton.setObjectName("pushButton")
        self.pushButton.setText("暂停策略")
        self.verticalLayout.addWidget(self.pushButton)

        self.pushButton_2 = QtWidgets.QPushButton(self.groupBox)
        self.pushButton_2.setObjectName("pushButton_2")
        self.pushButton_2.setText("继续策略")
        self.verticalLayout.addWidget(self.pushButton_2)

        self.horizontalLayout.addWidget(self.groupBox)

        self.verticalLayoutRight = QtWidgets.QVBoxLayout()
        self.verticalLayoutRight.setObjectName("verticalLayoutRight")

        self.groupBox_2 = QtWidgets.QGroupBox(self.centralwidget)
        self.groupBox_2.setObjectName("groupBox_2")
        self.verticalLayoutInfo = QtWidgets.QVBoxLayout(self.groupBox_2)
        self.verticalLayoutInfo.setObjectName("verticalLayoutInfo")

        self.label = QtWidgets.QLabel(self.groupBox_2)
        self.label.setObjectName("label")
        self.label.setText("当前账户名称：")
        self.verticalLayoutInfo.addWidget(self.label)

        self.label_2 = QtWidgets.QLabel(self.groupBox_2)
        self.label_2.setObjectName("label_2")
        self.label_2.setText("账户余额：")
        self.verticalLayoutInfo.addWidget(self.label_2)

        self.label_3 = QtWidgets.QLabel(self.groupBox_2)
        self.label_3.setObjectName("label_3")
        self.label_3.setText("浮动收益：")
        self.verticalLayoutInfo.addWidget(self.label_3)

        self.verticalLayoutRight.addWidget(self.groupBox_2)

        self.groupBox_3 = QtWidgets.QGroupBox(self.centralwidget)
        self.groupBox_3.setObjectName("groupBox_3")
        self.verticalLayoutTable = QtWidgets.QVBoxLayout(self.groupBox_3)
        self.verticalLayoutTable.setObjectName("verticalLayoutTable")

        self.tableWidget = QtWidgets.QTableWidget(self.groupBox_3)
        self.tableWidget.setColumnCount(5)
        self.tableWidget.setRowCount(0)
        self.tableWidget.setObjectName("tableWidget")
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(0, item)
        item.setText("持仓方向")
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(1, item)
        item.setText("持仓量")
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(2, item)
        item.setText("开仓价")
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(3, item)
        item.setText("当前价格")
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(4, item)
        item.setText("当前收益")
        self.verticalLayoutTable.addWidget(self.tableWidget)

        self.verticalLayoutRight.addWidget(self.groupBox_3)
        self.horizontalLayout.addLayout(self.verticalLayoutRight)

        CTBAS.setCentralWidget(self.centralwidget)
        self.retranslateUi(CTBAS)
        QtCore.QMetaObject.connectSlotsByName(CTBAS)

    def retranslateUi(self, CTBAS):
        _translate = QtCore.QCoreApplication.translate
        CTBAS.setWindowTitle(_translate("CTBAS", "CTBAS"))
        self.groupBox.setTitle(_translate("CTBAS", "输出日志"))
        self.pushButton.setText(_translate("CTBAS", "暂停策略"))
        self.pushButton_2.setText(_translate("CTBAS", "继续策略"))
        self.groupBox_2.setTitle(_translate("CTBAS", "基本信息"))
        self.label.setText(_translate("CTBAS", "当前账户名称："))
        self.label_2.setText(_translate("CTBAS", "账户余额："))
        self.label_3.setText(_translate("CTBAS", "浮动收益："))
        self.groupBox_3.setTitle(_translate("CTBAS", "持仓管理"))
