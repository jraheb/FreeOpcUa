from pathlib import Path
from datetime import datetime
BASE_DIR = Path.cwd().parent


def status_codes():
    """
    Load values from StatusCode.csv and then
    add values from StatusCodes_add.csv, but only
    if they are absent from StatusCode.csv
    """
    with open(BASE_DIR / 'schemas' / 'StatusCodes_add.csv') as inputfile:
        additional = {}
        for line in inputfile:
            name, val, doc = line.split(",", 2)
            additional[int(val, 0)] = (name, val, doc)
    with open(BASE_DIR / 'schemas' / 'UA-Nodeset-master' / 'Schema' / 'StatusCode.csv') as inputfile:
        result = []
        for line in inputfile:
            name, val, doc = line.split(",", 2)
            result.append((name, val, doc))
            additional.pop(int(val, 0), None)
        add = [additional[k] for k in sorted(additional.keys())]
    return add + result


if __name__ == "__main__":
    codes = status_codes()
    with open(BASE_DIR / "asyncua" / "ua" / "status_codes.py", "w") as outputfile:
        outputfile.write(f"#AUTOGENERATED!!! Date: {datetime.utcnow()}\n"
                         f"\n"
                         f"from asyncua.ua.uaerrors import UaStatusCodeError\n"
                         # outputfile.write("from enum import Enum\n")
                         f"\n")

        outputfile.write("class StatusCodes:\n")
        for name, val, doc in codes:
            doc = doc.strip()
            outputfile.write("    {0} = {1}\n".format(name, val))
        outputfile.write(f"\n\n")
        outputfile.write("code_to_name_doc = {\n")
        for name, val, doc in codes:
            doc = doc.strip()
            doc = doc.replace("'", '"')
            outputfile.write("    {0}: ('{1}', '{2}'),\n".format(val, name, doc))
        outputfile.write("}\n"
                         f"\n"
                         f"\n")

        outputfile.write("""def get_name_and_doc(val):
        if val in code_to_name_doc:
            return code_to_name_doc[val]
        else:
            if val & 1 << 31:
                return 'Bad', 'Unknown StatusCode value: {}'.format(val)
            elif val & 1 << 30:
                return 'UncertainIn', 'Unknown StatusCode value: {}'.format(val)
            else:
                return 'Good', 'Unknown StatusCode value: {}'.format(val)
    """)
