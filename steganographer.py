"""
    NOTE : 
        If you are using this code, then please give me Credits and leave a link to my GitHub Account.
        Don't forget to Star this repository 

        Code written by : Priyansh Anand
        Repository      : priyansh-anand/steganographer
        E-Mail          : contact.priyanshanand@gmail.com & developer.priyanshanand@gmail.com
        GitHub          : https://github.com/priyansh-anand

    * If you have any suggestion or improvements for this Module, then ping me!
    * Report if you find any bugs or error in this Module

"""


from PIL import Image

from getopt import getopt
from sys import argv


def __change_last_2_bits__(original_number, new_bits):
    """
    This function replaces the last ( LSBs ) 2 bits of the given original_number with new_bits

    Parameters
        ----------
        original_number : int
            The integer whose last 2 bits are to be changed
        new_bits : int
            This number can be {0,1,2,3}. These are the two bits that will overwrite the orginal_number

    Returns
        ----------
        int
            The modified integer with replaced bits
    """
    # First shift bits to left 2 times
    # Then shift bits to right 2 times, now we lost the last 2 bits
    # Perform OR operation between original_number and new_bits

    return original_number >> 2 << 2 | new_bits


def hide_data_to_image(input_file_path, data_to_hide, output_file_path):
    """
    This function hides the data_to_hide inside the image located at input_file_path,
    and saves this modified image to output_file_path.

    DOESN'T WORK WITH JPEG IMAGES, PNG ARE FULLY SUPPORTED

    ## In future, it will also support Encryption of the data_to_hide by default

    Parameters
        ----------
        input_file_path : str
            The path to the image file in which data is to be hidden
        data_to_hide : bytes
            The data to be hidden in input image file
        output_file_path : str
            The path to the modified image file with the hidden data

    """
    image = Image.open(input_file_path).convert('RGB')
    pixels = image.load()

    # End data_to_hide with 4 '\0' characters
    data_to_hide += b"\0\0\0\0"

    print(f"* INFO : Size of data to be hidden : {len(data_to_hide)} bytes")
    print(f"* INFO : Max Size of data that can be hidden : {(image.size[0]*image.size[1]*6)//8} bytes")

    if len(data_to_hide) > (image.size[0]*image.size[1]*6) // 8:
        print("* ERROR : Cannot hide file inside Image")
        print("* ERROR : Size of file to be hidden exceeds max file size")
        print("* TIP \t: Choose a bigger resolution image, 4K or 8K")
        return

    # We will break the data into chunks of 2 bits and save it to this stack in
    # reversed order ( So that we can pop elements )
    data_stack = list()

    for data in data_to_hide:
        data = bytes([data])
        data = int.from_bytes(data,byteorder="big")                                # Get integer value of byte
        chunk_stack = list()

        for i in range(4):                              # Extracting 2 bits 4 times, 8 bits or 1 byte
            last_two_bits = data & 0b11                 # Extract last two bits
            chunk_stack.append(last_two_bits)           # Push these bits to stack in reversed order
            data = data >> 2                            # Remove those last two bits

        chunk_stack.reverse()                           # Correct the order of chunk_stack
        data_stack.extend(chunk_stack)                  # Push items in correct order

    while len(data_stack) % 3 != 0:
        # Make the length of stack divisible by 3 so that we can hide data properly in a Pixel
        # Because in one pixel we can hide 3 times 2 bits ( one element of this list )
        data_stack.append(0)

    data_stack.reverse()                                # Reverse the data_stack to that we can pop elements

    image_x_index, image_y_index = 0,0

    while data_stack:
        # Pixel at index x and y
        pixel_val = pixels[image_x_index, image_y_index]

        # Hiding data in all 3 channels of each Pixel
        pixel_val = ( __change_last_2_bits__(pixel_val[0], data_stack.pop()),
                      __change_last_2_bits__(pixel_val[1], data_stack.pop()),
                      __change_last_2_bits__(pixel_val[2], data_stack.pop()))

        # Save pixel changes to Image
        pixels[image_x_index, image_y_index] = pixel_val

        if image_x_index == image.size[0] - 1:          # If reached the end of X Axis
            # Increment on Y Axis and reset X Axis
            image_x_index = 0
            image_y_index += 1
        else:
            # Increment on X Axis
            image_x_index += 1
    
    print(f"* INFO : Saving image to {output_file_path}")
    image.save(output_file_path)


def extract_message_from_image(input_file_path, output_file_path):
    """
    This function extracts the hidden data from the image located at input_file_path,
    and saves this extraced data to output_file_path.

    ## In future it will also support automatic extension ( file type ) detection of the hidden file data

    Parameters
        ----------
        input_file_path : str
            The path to the image file in which the data is hidden
        output_file_path : str
            The path to the output file to save the extracted hidden file data

    """
    image = Image.open(input_file_path).convert('RGB')
    pixels = image.load()

    data_stack = list()                                 # List where we will store the extracted bits
    break_loop = False

    for image_y_index in range(image.size[1]):
        for image_x_index in range(image.size[0]):
            # Read pixel values traversing from [0, 0] to the end
            pixel = pixels[image_x_index, image_y_index]

            # Extract hidden message in chunk of 2 bits from each Channel
            data_stack.append(pixel[0] & 0b11)
            data_stack.append(pixel[1] & 0b11)
            data_stack.append(pixel[2] & 0b11)

            if len(data_stack) >= 16 and set(data_stack[-16:]) == set(b"\x00"):
                # We encountered 4 '\0' characters, that means our hidden message ends here
                break_loop = True
                break
        
        if break_loop:
            break
    
    if not break_loop:
        # That means we didn't encountered any '\0' character
        print("WARNING : Incomplete Hidden Message")
        print("WARNING : Image may be corrupted or no Message was hidden in this Image")


    data = bytes()

    for i in range(0,len(data_stack) - 4, 4):
        # Extract 2 bits 4 times i.e 8 bits ( We will get one UTF-8 Character)
        chunk = data_stack[i:i + 4]

        # The integer value of byte we will extract from the image
        recovered_int = 0

        recovered_int |= chunk[0] << 6                  # Extracting 8th and 7th bit respectively
        recovered_int |= chunk[1] << 4                  # Extracting 6th and 5th bit respectively
        recovered_int |= chunk[2] << 2                  # Extracting 4th and 3rd bit respectively
        recovered_int |= chunk[3]                       # Extracting 2nd and 1st bit respectively

        if len(data) >= 3 and recovered_int == 0 and set(data[-3:]) == set(b"\x00"):
            # 4 '\0' characters found, end of hidden file
            data += bytes([recovered_int])
            break
        else:
            data += bytes([recovered_int])              # Putting extracted byte (8 bits) to the right place 
    
    if break_loop:                                      # If the hidden file is complete
        data = data[:-4]                                # Remove last 4 '\0' characters

    print(f"* INFO : Saving hidden file to {output_file_path}")
    print(f"* INFO : Size of hidden file recovered : {len(data)} bytes")
    f = open(output_file_path,'wb')
    f.write(data)
    f.close()


def main():
    options,remainder = getopt(argv[1:],"eh:i:o:")

    input_file_path = str()
    file_to_be_hidden_path = str()
    output_file_path = str()

    extract_hidden_file_from_image = False

    for opt, arg in options:
        if opt == "-i":
            input_file_path = arg
        elif opt == "-h":
            file_to_be_hidden_path = arg
        elif opt == "-e":
            extract_hidden_file_from_image = True
        elif opt == "-o":
            output_file_path = arg
    
    if not (input_file_path and (extract_hidden_file_from_image or file_to_be_hidden_path)):
        print("Usage: python3 steganographer.py [-i input_file_path] [-h file_to_hide] [-o ouput_file_path] [-e]")
        print("\t-i path to input image file")
        print("\t-h path to file to be hidden \t( if you want to hide a file in an image )")
        print("\t-e extract hidden file\t\t( if you want to extract hidden file from image)")
        print("\t-o path to output image file \t( optional )")
    else:
        if extract_hidden_file_from_image:
            if not output_file_path:
                output_file_path = ".".join(input_file_path.split(".")[:-1]) + "_hidden_file" + "." + "txt"  # Will add extension detection in future

            extract_message_from_image(input_file_path, output_file_path)
        else:
            file_to_be_hidden = open(file_to_be_hidden_path,"rb")

            if not output_file_path:
                output_file_path = ".".join(input_file_path.split(".")[:-1]) + "_with_hidden_file" + "." + input_file_path.split(".")[-1]
            
            data_to_be_hidden = file_to_be_hidden.read()

            hide_data_to_image(input_file_path, data_to_be_hidden, output_file_path)


if __name__ == '__main__':
    main()
