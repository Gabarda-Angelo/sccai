<!-- editproduct.php (POS component) -->
<?php
include_once 'connectdb.php';
session_start();
include_once "header.php";

// Get the product ID from the query string
$id = $_GET['id'];

// Fetch product details from the "products" table
$select = $pdo->prepare("SELECT * FROM products WHERE product_id = :id");
$select->bindParam(':id', $id, PDO::PARAM_INT);
$select->execute();
$row = $select->fetch(PDO::FETCH_ASSOC);

$id_db             = $row['product_id'];
$barcode_db        = $row['barcode'];
$product_db        = $row['product_name'];
$category_db       = $row['category_id']; // Numeric value from products table
$description_db    = $row['description'];
$stock_db          = $row['stock'];
$purchaseprice_db  = $row['purchase_price'];
$saleprice_db      = $row['sale_price'];
$image_db          = $row['image'];

if (isset($_POST['btneditproduct'])) {
    // Retrieve posted form values
    $product_txt       = $_POST['txtproductname'];
    $category_txt      = $_POST['txtselect_option']; // This is the category_id
    $description_txt   = $_POST['txtdescription'];
    $stock_txt         = $_POST['txtstock'];
    $purchaseprice_txt = $_POST['txtpurchaseprice'];
    $saleprice_txt     = $_POST['txtsaleprice'];

    // Check if a new image file is uploaded
    $f_name = $_FILES['myfile']['name'];

    if (!empty($f_name)) {
        // Process the uploaded image file
        $f_tmp       = $_FILES['myfile']['tmp_name'];
        $f_size      = $_FILES['myfile']['size'];
        $f_extension = explode('.', $f_name);
        $f_extension = strtolower(end($f_extension));

        $f_newfile = uniqid() . '.' . $f_extension;
        $store     = "productimages/" . $f_newfile;

        // Allowed file types: jpg, jpeg, png
        if ($f_extension == 'jpg' || $f_extension == 'jpeg' || $f_extension == 'png') {
            if ($f_size >= 1000000) {
                $_SESSION['status'] = "Max file size should be 1MB";
                $_SESSION['status_code'] = "warning";
            } else {
                if (move_uploaded_file($f_tmp, $store)) {
                    // Update the product record with the new image filename
                    $update = $pdo->prepare("UPDATE products 
                        SET product_name = :product, 
                            category_id = :category, 
                            description = :description, 
                            stock = :stock, 
                            purchase_price = :pprice, 
                            sale_price = :sprice, 
                            image = :image 
                        WHERE product_id = :id");

                    $update->bindParam(':product', $product_txt);
                    $update->bindParam(':category', $category_txt);
                    $update->bindParam(':description', $description_txt);
                    $update->bindParam(':stock', $stock_txt);
                    $update->bindParam(':pprice', $purchaseprice_txt);
                    $update->bindParam(':sprice', $saleprice_txt);
                    $update->bindParam(':image', $f_newfile);
                    $update->bindParam(':id', $id, PDO::PARAM_INT);

                    if ($update->execute()) {
                        $_SESSION['status'] = "Product Updated Successfully With New Image";
                        $_SESSION['status_code'] = "success";
                    } else {
                        $_SESSION['status'] = "Product Image Update Failed";
                        $_SESSION['status_code'] = "error";
                    }
                }
            }
        } else {
            $_SESSION['status'] = "Only jpg, jpeg, and png files are allowed";
            $_SESSION['status_code'] = "warning";
        }
    } else {
        // No new image uploaded; keep the existing image
        $update = $pdo->prepare("UPDATE products 
            SET product_name = :product, 
                category_id = :category, 
                description = :description, 
                stock = :stock, 
                purchase_price = :pprice, 
                sale_price = :sprice, 
                image = :image 
            WHERE product_id = :id");

        $update->bindParam(':product', $product_txt);
        $update->bindParam(':category', $category_txt);
        $update->bindParam(':description', $description_txt);
        $update->bindParam(':stock', $stock_txt);
        $update->bindParam(':pprice', $purchaseprice_txt);
        $update->bindParam(':sprice', $saleprice_txt);
        $update->bindParam(':image', $image_db);
        $update->bindParam(':id', $id, PDO::PARAM_INT);

        if ($update->execute()) {
            $_SESSION['status'] = "Product Updated Successfully";
            $_SESSION['status_code'] = "success";
        } else {
            $_SESSION['status'] = "Product Update Failed";
            $_SESSION['status_code'] = "error";
        }
    }
}

// Re-fetch product details after update to reflect changes
$select = $pdo->prepare("SELECT * FROM products WHERE product_id = :id");
$select->bindParam(':id', $id, PDO::PARAM_INT);
$select->execute();
$row = $select->fetch(PDO::FETCH_ASSOC);

$id_db             = $row['product_id'];
$barcode_db        = $row['barcode'];
$product_db        = $row['product_name'];
$category_db       = $row['category_id'];
$description_db    = $row['description'];
$stock_db          = $row['stock'];
$purchaseprice_db  = $row['purchase_price'];
$saleprice_db      = $row['sale_price'];
$image_db          = $row['image'];
?>

<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <!-- Optional: Page Title or Breadcrumbs -->
                </div>
                <div class="col-sm-6">
                    <ol class="breadcrumb float-sm-right">
                        <!-- Breadcrumbs can go here -->
                    </ol>
                </div>
            </div>
        </div>
    </div>
    <!-- /.content-header -->

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <div class="card card-success card-outline">
                        <div class="card-header">
                            <h5 class="m-0">Edit Product</h5>
                        </div>
                        <form action="" method="post" name="formeditproduct" enctype="multipart/form-data">
                            <div class="card-body">
                                <div class="row">
                                    <!-- Left Column -->
                                    <div class="col-md-6">
                                        <div class="form-group">
                                            <label>Barcode</label>
                                            <!-- Barcode is shown but not editable -->
                                            <input type="text" class="form-control" value="<?php echo $barcode_db; ?>" placeholder="Enter Barcode" name="txtbarcode" autocomplete="off" disabled>
                                        </div>
                                        <div class="form-group">
                                            <label>Product Name</label>
                                            <input type="text" class="form-control" value="<?php echo $product_db; ?>" placeholder="Enter Name" name="txtproductname" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Category</label>
                                            <select class="form-control" name="txtselect_option" required>
                                                <option value="" selected disabled>Select Category</option>
                                                <?php
                                                // Fetch categories from the "categories" table
                                                $select_cat = $pdo->prepare("SELECT * FROM categories ORDER BY category_name ASC");
                                                $select_cat->execute();
                                                while ($row_cat = $select_cat->fetch(PDO::FETCH_ASSOC)) {
                                                    ?>
                                                    <option value="<?php echo $row_cat['category_id']; ?>" <?php if ($row_cat['category_id'] == $category_db) { echo 'selected="selected"'; } ?>>
                                                        <?php echo $row_cat['category_name']; ?>
                                                    </option>
                                                    <?php
                                                }
                                                ?>
                                            </select>
                                        </div>
                                        <div class="form-group">
                                            <label>Description</label>
                                            <textarea class="form-control" placeholder="Enter Description" name="txtdescription" rows="4" required><?php echo $description_db; ?></textarea>
                                        </div>
                                    </div>
                                    <!-- Right Column -->
                                    <div class="col-md-6">
                                        <div class="form-group">
                                            <label>Stock Quantity</label>
                                            <input type="number" min="1" class="form-control" value="<?php echo $stock_db; ?>" placeholder="Enter Stock" name="txtstock" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Purchase Price</label>
                                            <input type="number" min="0" step="0.01" class="form-control" value="<?php echo $purchaseprice_db; ?>" placeholder="Enter Purchase Price" name="txtpurchaseprice" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Sale Price</label>
                                            <input type="number" min="0" step="0.01" class="form-control" value="<?php echo $saleprice_db; ?>" placeholder="Enter Sale Price" name="txtsaleprice" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Product Image</label><br>
                                            <img src="productimages/<?php echo $image_db; ?>" class="img-rounded" width="50" height="50" alt="Product Image">
                                            <input type="file" class="input-group" name="myfile">
                                            <p>Upload Image (leave blank to keep current image)</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <!-- /.card-body -->
                            <div class="card-footer text-center">
                                <button type="submit" class="btn btn-success" name="btneditproduct">Update Product</button>
                            </div>
                        </form>
                    </div>
                </div>
                <!-- /.col-lg-12 -->
            </div>
            <!-- /.row -->
        </div>
        <!-- /.container-fluid -->
    </div>
    <!-- /.content -->
</div>
<!-- /.content-wrapper -->

<?php include_once "footer.php"; ?>

<?php
if (isset($_SESSION['status']) && $_SESSION['status'] != '') {
?>
    <script>
        Swal.fire({
            icon: '<?php echo $_SESSION['status_code']; ?>',
            title: '<?php echo $_SESSION['status']; ?>'
        });
    </script>
<?php
    unset($_SESSION['status']);
}
?>
