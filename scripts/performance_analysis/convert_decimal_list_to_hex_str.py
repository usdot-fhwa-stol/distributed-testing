def decimal_to_hex(decimal_values):
    # Convert each decimal value to hexadecimal and format with leading zeros
    hex_values = [format(int(value), '02X') for value in decimal_values]
    return hex_values

def main():
    # Prompt user for input
    user_input = input("Enter a list of decimal values separated by commas, tabs, or spaces: ")
    
    # Determine the separator used in the input
    if ',' in user_input:
        decimal_values = user_input.split(',')
    elif '\t' in user_input:
        decimal_values = user_input.split('\t')
    else:
        decimal_values = user_input.split()
    
    # Convert decimal values to hexadecimal
    hex_values = decimal_to_hex(decimal_values)
    
    # Join the hexadecimal values into a single string without commas
    hex_string = ''.join(hex_values)
    
    # Print the result
    print("Hexadecimal string:", hex_string)

if __name__ == "__main__":
    main()