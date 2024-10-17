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


if __name__=="__main__":
    parser = argparse.ArgumentParser(description='CppCheck Resolver')
    parser.add_argument('args', nargs='*', help='target folder or android_home')
    parser.add_argument('--cppcheck', default=os.path.dirname(os.path.abspath(__file__))+"/../CppChecker/CppChecker.rb", help='Specify the path for CppChecker.rb')

    args = parser.parse_args()

    for target_path in args.args:
        exec_cmd = f'ruby {args.cppcheck} {target_path} -m detail -s --detailSection=\"filename|line|message|\"'
        result = ExecUtil.getExecResultEachLine(exec_cmd, target_path, False)
        for line in result:
            print(line)