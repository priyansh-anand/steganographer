"""
    NOTE : 
        If you are using this code, then please give me credits and leave a link to my GitHub Account.
        Don't forget to star this repository 

        Code written by : Priyansh Anand
        Repository      : priyansh-anand/steganographer
        E-Mail          : contact.priyanshanand@gmail.com & developer.priyanshanand@gmail.com
        GitHub          : https://github.com/priyansh-anand

    * If you have any suggestion or improvements for this script, then ping me!
    * Report if you find any bugs or error in this Module

"""

from PIL import Image

from getopt import getopt
from sys import argv

def changeLast2Bits(origByte: int, newBits: int) -> int:
    """
    This function replaces the 2 LSBs of the given origByte with newBits
    """
    # First shift bits to left 2 times
    # Then shift bits to right 2 times, now we lost the last 2 bits
    # Perform OR operation between original_number and new_bits

    return (origByte >> 2) << 2 | newBits

def filesizeToBytes(data: bytes) -> bytes:
    """
    This function returns the size of data in 8 bytes
    """
    return (len(data)).to_bytes(8, byteorder='big')

def serializeData(data: bytes, padding: int = 1) -> list:
    """
    This function packs data into groups of 2bits and returns that list
    """
    serializedData = list()
    for datum in data:
        serializedData.append((datum >> 6) & 0b11)
        serializedData.append((datum >> 4) & 0b11)
        serializedData.append((datum >> 2) & 0b11)
        serializedData.append((datum >> 0) & 0b11)

    while len(serializedData) % padding != 0:
        serializedData.append(0)

    return serializedData

def deserializeData(data: list) -> bytes:
    """
    This function takes data and unpacks the '2bits groups' to get original data back
    """
    deserializeData = list()
    for i in range(0, len(data) - 4 + 1, 4):
        datum = (data[i] << 6) + (data[i + 1] << 4) + (data[i + 2] << 2) + (data[i + 3] << 0)
        deserializeData.append(datum)
    
    return bytes(deserializeData)

def hideDataToImage(inputImagePath, fileToHidePath, outputImagePath):
    """
    This function hides the fileToHidePath file inside the image located at inputImagePath,
    and saves this modified image to outputImagePath.
    """

    image = Image.open(inputImagePath).convert('RGB')
    pixels = image.load()

    fp = open(fileToHidePath,"rb")

    data = fp.read()
    print("[*] {} file size : {} bytes".format(fileToHidePath, len(data)))

    data = (0xDEADC0DE).to_bytes(4, byteorder='big') + filesizeToBytes(data) + data
    if len(data) > (image.size[0] * image.size[1] * 6) // 8:
        print("[*] Maximum hidden file size exceeded")
        print("[*] Maximum hidden file size for this image: {}".format( (image.size[0] * image.size[1] * 6) // 8 ))
        print("[~] To hide this file, choose a bigger resolution")
        exit()

    print("[*] Hiding file in image")
    data = serializeData(data, padding=3)
    data.reverse()

    imageX, imageY = 0,0
    while data:
        # Pixel at index x and y
        pixel_val = pixels[imageX, imageY]

        # Hiding data in all 3 channels of each Pixel
        pixel_val = ( changeLast2Bits(pixel_val[0], data.pop()),
                      changeLast2Bits(pixel_val[1], data.pop()),
                      changeLast2Bits(pixel_val[2], data.pop()))

        # Save pixel changes to Image
        pixels[imageX, imageY] = pixel_val

        if imageX == image.size[0] - 1:          # If reached the end of X Axis
            # Increment on Y Axis and reset X Axis
            imageX = 0
            imageY += 1
        else:
            # Increment on X Axis
            imageX += 1
    
    if not outputImagePath:
        outputImagePath = ".".join(inputImagePath.split(".")[:-1]) + "_with_hidden_file" + "." + inputImagePath.split(".")[-1]
    
    print(f"[+] Saving image to {outputImagePath}")
    image.save(outputImagePath)

def extractDataFromImage(inputImagePath, outputFilePath):
    """
    This function extracts the hidden file from inputImagePath image and saves it to outputFilePath
    """

    image = Image.open(inputImagePath).convert('RGB')
    pixels = image.load()

    data = list()                                 # List where we will store the extracted bits
    for imageY in range(image.size[1]):
        for imageX in range(image.size[0]):
            if len(data) >= 48:
                break
            
            # Read pixel values traversing from [0, 0] to the end
            pixel = pixels[imageX, imageY]

            # Extract hidden message in chunk of 2 bits from each Channel
            data.append(pixel[0] & 0b11)
            data.append(pixel[1] & 0b11)
            data.append(pixel[2] & 0b11)

    if deserializeData(data)[:4] != bytes.fromhex("deadc0de"):
        print("[!] Image don't have any hidden data")
        print("[*] Magic bytes found:    0x{}".format(deserializeData(data)[:4].hex()))
        print("[*] Magic bytes expected: {}".format("0xdeadc0de"))
        exit()

    print("[*] Extracting hidden file from image")
    hiddenDataSize = int.from_bytes(deserializeData(data)[4:16], byteorder='big') * 4

    data = list()
    for imageY in range(image.size[1]):
        for imageX in range(image.size[0]):
            if len(data) >= hiddenDataSize + 48:
                break 

            # Read pixel values traversing from [0, 0] to the end
            pixel = pixels[imageX, imageY]

            # Extract hidden message in chunk of 2 bits from each Channel
            data.append(pixel[0] & 0b11)
            data.append(pixel[1] & 0b11)
            data.append(pixel[2] & 0b11)

    data = deserializeData(data[48:])

    print(f"[+] Saving hidden file to {outputFilePath}")
    print(f"[*] Size of hidden file recovered : {len(data)} bytes")

    f = open(outputFilePath,'wb')
    f.write(data)
    f.close()


def main():
    options, _ = getopt(argv[1:],"eh:i:o:")

    inputImagePath = str()
    hiddenFilePath = str()
    outputImagePath = str()

    extractionMode = False

    for opt, arg in options:
        if opt == "-i":
            inputImagePath = arg
        elif opt == "-h":
            hiddenFilePath = arg
        elif opt == "-e":
            extractionMode = True
        elif opt == "-o":
            outputImagePath = arg
    
    if not (inputImagePath and hiddenFilePath):
        print("Usage: python3 steganographer.py [-i inputImagePath] [-h hiddenFilePath] [-o outputImagePath] [-e]")
        print("\t-i path to input image file")
        print("\t-h path to (extract/hide) hidden file")
        print("\t-e extract hidden file \t\t\t(optional)")
        print("\t-o path to output image file (PNG only) (optional)")
    else:
        if extractionMode:
            extractDataFromImage(inputImagePath, hiddenFilePath)
        else:
            if not outputImagePath:
                outputImagePath = "".join(inputImagePath.split(".")[:-1]) + "_steg0.png"
            if not outputImagePath.endswith(".png"):
                print("[!] Output image should be a PNG")
                exit()

            hideDataToImage(inputImagePath, hiddenFilePath, outputImagePath)

if __name__ == '__main__':
    main()
