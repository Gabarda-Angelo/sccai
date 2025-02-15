<!-- barcode.php (POS component) -->
<html>
<head>
  <style>
    p.inline { display: inline-block; }
    span { font-size: 13px; }
  </style>
  <style type="text/css" media="print">
    @page {
      size: auto;   /* auto is the initial value */
      margin: 0mm;  /* this affects the margin in the printer settings */
    }
  </style>
</head>
<body onload="window.print();">
  <div style="margin-left: 5%">
    <?php
    include 'barcode128.php';

    // Use isset() to avoid undefined index errors.
    // Note: 'product' is not being sent by your form, so you can either set a default value or update your form.
    $product   = isset($_POST['product']) ? $_POST['product'] : 'Unknown Product';
    $barcode   = isset($_POST['barcode']) ? $_POST['barcode'] : '';
    // Use the key "price" because that's what your form sends, not "rate".
    $rate      = isset($_POST['price']) ? $_POST['price'] : '0.00';
    $print_qty = isset($_POST['print_qty']) ? (int)$_POST['print_qty'] : 1;

    for ($i = 1; $i <= $print_qty; $i++) {
        echo "<p class='inline'><span><b>Item: $product</b></span>" 
             . bar128(stripcslashes($barcode)) 
             . "<span><b>Price: $rate</b></span></p>&nbsp;&nbsp;&nbsp;&nbsp;";
    }
    ?>
  </div>
</body>
</html>
