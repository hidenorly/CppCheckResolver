#   Copyright 2024 hidenorly
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import argparse
import os
from ExecUtil import ExecUtil

class CppCheckerUtil:
    def __init__(self, cppchecker_path):
        self.cppchecker_path = cppchecker_path

    def parse_line(self, line):
        filename = None
        line_number = None
        message = None

        if line.startswith("| "):
            pos = line.find(" | ")
            if pos!=None:
                filename = line[2:pos]
                line = line[pos+3:]
                pos = line.find(" | ")
                if pos!=None:
                    try:
                        line_number = int(line[0:pos])
                    except:
                        pass
                    line = line[pos+3:]
                    pos = line.find(" |")
                    if pos!=None:
                        message = line[0:pos]

        if filename=="filename" or filename==":---":
            filename=None
        if message==":---":
            message=None

        return filename, line_number, message

    def parse_result(self, lines, target_path=None):
        result = {}
        for line in lines:
            filename, line_number, message = self.parse_line(line)
            if filename and line_number and message:
                if not target_path or os.path.exists(os.path.join(target_path, filename)):
                    if not filename in result:
                        result[filename] = []
                    result[filename].append( [line_number, message] )
        return result


    def execute(self, target_path):
        exec_cmd = f'ruby {self.cppchecker_path} {target_path} -m detail -s --detailSection=\"filename|line|message|\"'

        result = self.parse_result(ExecUtil.getExecResultEachLine(exec_cmd, target_path, False), target_path)

        return result



if __name__=="__main__":
    parser = argparse.ArgumentParser(description='CppCheck Resolver')
    parser.add_argument('args', nargs='*', help='target folder or android_home')
    parser.add_argument('--cppcheck', default=os.path.dirname(os.path.abspath(__file__))+"/../CppChecker/CppChecker.rb", help='Specify the path for CppChecker.rb')

    args = parser.parse_args()

    if os.path.exists(args.cppcheck):
        cppchecker = CppCheckerUtil(args.cppcheck)

        for target_path in args.args:
            results = cppchecker.execute(target_path)
            for filename, reports in results.items():
                for report in reports:
                    print(f"{filename},{report[0]},{report[1]}")