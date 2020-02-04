import json
import cv2 
import requests
import numpy as np
''' RULES

* At least one image per SKU required. Products without images are ignored
* RGB Images only, no CMYK
* Supported formats: JPG, PNG
* Minimum resolution: 1200 px (longer edge)
* Maximum resolution: 100 Mpx (width x height. Eg. 10000 x 10000 px for 1.0 aspect ratio)
* Do not include extra whitespace in rectangular / scene imagery
* URL must return proper content-length header for the image file, try to avoid redirects
'''

supported_types = ['image/png', 'image/jpeg', 'image/jpg']

def findBox(img, estimate = False, bounds = None, tolerance = 1):
    rows, cols = img.shape
    if rows < 200 or cols < 200:
        return (0,cols-1,0,rows-1)
    
    left_bound, right_bound, upper_bound, lower_bound = 0,cols-1,0,rows-1
    if bounds:
        left_bound, right_bound, upper_bound, lower_bound = bounds
        
    step, shift = 1, 0
    
    if estimate:
        step = int(min(rows, cols)/100)
        shift = step

    for i in range(upper_bound, rows, step):
        value = round(sum(img[i, :])/cols, 2)
        if value < 255 - tolerance:
            upper_bound = i
            break
    
    for i in range(lower_bound, 0, -step):
        value = round(sum(img[i, :])/cols, 2)
        if value < 255 - tolerance:
            lower_bound = i
            break
            
    for j in range(left_bound, cols, step):
        value = round(sum(img[:, j])/rows, 2)
        if value  < 255 - tolerance:
            left_bound = j
            break
            
    for j in range(right_bound, 0, -step):
        value = round(sum(img[:, j])/rows, 2)
        if value < 255 - tolerance:
            right_bound = j
            break
    
    #prevent from going out of boundary
    if estimate:
        left_bound =  (left_bound - shift if left_bound - shift >= 0 else 0)
        right_bound = (right_bound + shift if right_bound + shift < cols else cols-1)     
        upper_bound = (upper_bound - shift if upper_bound - shift >= 0 else 0)
        lower_bound = (lower_bound + shift if lower_bound + shift < rows else rows-1)

    left_bound =  (left_bound if left_bound >= 0 else 0)
    right_bound = (right_bound if right_bound < cols else cols-1)
    upper_bound = (upper_bound if upper_bound >= 0 else 0)
    lower_bound = (lower_bound if lower_bound < rows else rows-1)
      
    if left_bound >= right_bound or upper_bound >= lower_bound:
        return (0,cols-1,0,rows-1)
    return (left_bound, right_bound, upper_bound, lower_bound)
    

def build_histgram(hist, key):
    if key in hist:
        hist[key] += 1
    else:
        hist[key] = 1
    

def findBound(img):
    bounds = findBox(img, estimate = True)
    left_bound, right_bound, upper_bound, lower_bound = findBox(img, bounds=bounds)
    
    # Identify Scene Image
    """
    Algorithm Concept
    Old:
    On the boundary line, if there are all non white points, it is scene image
    Otherwise it is single product image with white background
    
    New Version:
    1. If the boundary is at edge, ignore white pixels
    2. Otherwise, if more than 1 non white pixels, identify it as "Not Scene" image
    
    """
    boudary_pixels = (lower_bound - upper_bound + 1)*2 + (right_bound - left_bound + 1)*2
    histogram = {}
    for x in range(upper_bound, lower_bound):
        left_pixel = img[x, left_bound]
        right_pixel = img[x, right_bound]
        build_histgram(histogram, left_pixel)
        build_histgram(histogram, right_pixel)
        
    for y in range(left_bound, right_bound):
        up_pixel = img[upper_bound, y]
        low_pixel = img[lower_bound, y]
        build_histgram(histogram, up_pixel)
        build_histgram(histogram, low_pixel)
    
    white_pixel_count = 0
    for k in histogram:
        if k >= 254:
            white_pixel_count += histogram[k]
    
    #print(histogram)
    non_white_pixels_percent = (boudary_pixels-white_pixel_count)/boudary_pixels
    print('non white pixels percentage: ' + str(non_white_pixels_percent))
    
    return [upper_bound, lower_bound, left_bound, right_bound, non_white_pixels_percent > 0.9]

def isLargeMargin(img_area, box_area, threshold = 1): # If padding area is larger than 100% , then requires crop
    if box_area >= img_area:
        return False, 0
    percent = round((img_area-box_area)/box_area, 3)
    print('Padding Area is ' + str(round(percent*100,2)) + '%')
    return  percent > threshold, percent
    
def analyzeImage(url, downloadContent = True):
    url = url.replace('|', '&')
    #white_margin_percent = 0.05
    result = {   'URL_Status_Code':None, # Integer                              *
                      'Not_Image':False, # Boolean, it is not product if true . *
           'Invalid_ContentLength':True, # Boolean, url contains content length *
                 'Low_Resolution':False, # Boolean                              *
              'Resolution_TooHigh':None, # Boolean                              *
          'Unsupported_ImageType':False, # Boolean                              *
                    'Require_Crop':None, # Boolean  require crop or not         *
                  
           'Padding_Percent':None, # Float, caculated (Padding area/Product Area) ratio
                  'is_Scene':None, # Boolean, if it is a scene image
            'Image_DataType':None, # String, such as image/jpeg
               'Image_Shape':None  # Tuple,  contains image shape
             }
             
    try:
        response = requests.get(url, stream=True)
        result['URL_Status_Code'] = response.status_code
        result['Image_URL'] = url
    except Exception as e:
        print("error:", e)
        result={}
        result['Error'] = e
        return result
    print(url)
    
    ContentType = None
    if 'Content-Type' in response.headers:
            ContentType = response.headers['Content-Type']
#     for k in response.headers:
#         print(response.headers[k])
    if 'Content-Length' in response.headers:
        content_len = response.headers['Content-Length']
        print('Content Length: ' + str(content_len))
        if isinstance(content_len, str) and content_len.isdigit() and int(content_len) > 0:
            result['Invalid_ContentLength'] =  False
        if isinstance(content_len, int) and content_len > 0:
            result['Invalid_ContentLength'] =  False
    print(result['Invalid_ContentLength'])
    
    if ContentType:
        result['Unsupported_ImageType'] = ContentType.lower() not in supported_types

        result['Image_DataType'] = ContentType
    
    if not result['Invalid_ContentLength'] and downloadContent and response.status_code == 200 and not result['Unsupported_ImageType']:
        content = response.raw
        
        img = np.asarray(bytearray(content.read()), dtype="uint8")
        
        print('numpy image array size: ' + str(img.size))
        
        if img.size > 0:
            img = cv2.imdecode(img, cv2.IMREAD_COLOR)
            print('After decoding, img array size: ' + str(img.shape))
            img = cv2.cvtColor(img , cv2.COLOR_BGR2RGB)
            print('After color conversion, img array size: ' + str(img.shape))
            rows, cols, _ = img.shape
            result['Image_Shape'] = img.shape
            gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            print(' Gray image array size: ' + str(gray_img.shape))
            
            del img
            upper, lower, left, right, result['is_Scene'] = findBound(gray_img)
            del gray_img
            x1 = left
            y1 = upper
            x2 = right
            y2 = lower
            print(url)
            
            result['Resolution_TooHigh'] = rows*cols/1000000 >= 100 # Maximum resolution: 100 Mpx (width x height. Eg. 10000 x 10000 px for 1.0 aspect ratio)
            
            
            if rows < 1200 and cols < 1200:
                result['Low_Resolution'] = True
                
            result['Require_Crop'], result['Padding_Percent'] = isLargeMargin((rows-1)*(cols-1), pow(max(x2-x1, y2-y1), 2))
            
            if (result['Padding_Percent'] > 20):
                result['Not_Image'] = True
            result['Bound_Box'] = [(x1, y1), (x2, y2)]
    
            if result['is_Scene']:
                result['Require_Crop'] = result['Padding_Percent'] > 0
        else:
            result['error: '] = "image data not downloaded"
        
    return result

def lambda_handler(event, context):
    url = event['img_url']
    return analyzeImage(url)