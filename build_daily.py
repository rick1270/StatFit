from statfit import daily, sheets_writer

if __name__ == "__main__":
    sheet = sheets_writer.connect_sheet()
    n = daily.build_daily(sheet)
    print(f"Built Daily tab: {n} rows.")
